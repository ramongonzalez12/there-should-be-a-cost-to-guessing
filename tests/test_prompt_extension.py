"""The paid-run admission guard rejects plausible but invalid full matrices."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import export_prompt_extension as extension

from belowzero.contracts import PROMPT_ONLY_CONTRACTS
from belowzero.prompts import build_messages, messages_sha256


@pytest.fixture
def arm_db(tmp_path, monkeypatch):
    banks = {b: [{'item_id': f'{b}:{i}', 'question': f'Question {i}', 'kind': 'mc',
                  'choices': ['first', 'second'], 'reference': 'A'} for i in range(100)]
             for b in extension.BENCHES}
    monkeypatch.setattr(extension, 'BENCHMARKS', {b: (lambda n, b=b: banks[b][:n]) for b in banks})
    path = tmp_path / 'arm.db'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE answers (key TEXT, model TEXT, contract TEXT, benchmark TEXT, item_id TEXT, error TEXT, verdict TEXT, parse_failure INTEGER, reference TEXT)')
    con.execute('CREATE TABLE call_meta (key TEXT, request_json TEXT, rep INTEGER, finish_reason TEXT)')
    for bench, items in banks.items():
        for item in items:
            key = item['item_id']
            messages = build_messages(item, PROMPT_ONLY_CONTRACTS['quad_score_only'])
            request = {'model': 'test/model', 'messages': messages, 'messages_sha256': messages_sha256(messages),
                       'max_tokens': 4000, 'reasoning': {'enabled': False}, 'temperature': 0}
            con.execute('INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)',
                        (key, 'test/model', 'quad_score_only', bench, key, None, 'CORRECT', 0, 'A'))
            con.execute('INSERT INTO call_meta VALUES (?,?,?,?)', (key, json.dumps(request), 0, 'stop'))
    con.commit()
    con.close()
    return path


def validate(path):
    return extension.validate_arm(path, 'test/model', 'quad_score_only')


def test_exact_frozen_arm_is_admitted(arm_db):
    result = validate(arm_db)
    assert len(result['pilot']) == 8
    assert result['configuration']['max_tokens'] == 4000


@pytest.mark.parametrize('change, message', [
    ("DELETE FROM answers WHERE key='mmlu_pro:99'", 'exact frozen'),
    ("UPDATE answers SET item_id='different' WHERE key='mmlu_pro:99'", 'exact frozen'),
    ("UPDATE answers SET error='provider timeout' WHERE key='mmlu_pro:99'", 'provider error'),
    ("UPDATE answers SET reference='B' WHERE key='mmlu_pro:99'", 'reference'),
    ("UPDATE answers SET parse_failure=1 WHERE key='mmlu_pro:99'", 'malformed'),
    ("UPDATE call_meta SET request_json=json_set(request_json,'$.max_tokens',8000) WHERE key='mmlu_pro:99'", 'mixed inference'),
    ("UPDATE call_meta SET request_json=json_set(request_json,'$.messages[0].content','Different instruction') WHERE key='mmlu_pro:99'", 'prompt or question'),
])
def test_rejects_full_matrix_corruption(arm_db, change, message):
    with sqlite3.connect(arm_db) as con:
        con.execute(change)
    with pytest.raises(ValueError, match=message):
        validate(arm_db)


def test_completed_arm_cannot_hide_a_failed_pilot(arm_db):
    with sqlite3.connect(arm_db) as con:
        con.execute("UPDATE answers SET parse_failure=1,verdict='INCORRECT' WHERE key IN ('mmlu_pro:0','mmlu_pro:1','mmlu_pro:2')")
    with pytest.raises(ValueError, match='fails pilot'):
        validate(arm_db)


def test_two_of_twenty_uses_frozen_sixty_item_extension(arm_db):
    with sqlite3.connect(arm_db) as con:
        con.execute("UPDATE answers SET parse_failure=1,verdict='INCORRECT' WHERE key IN ('mmlu_pro:0','mmlu_pro:1','mmlu_pro:30')")
    assert validate(arm_db)['pilot'][0] == {'benchmark': 'mmlu_pro', 'n': 60, 'malformed': 3}
    with sqlite3.connect(arm_db) as con:
        con.execute("UPDATE answers SET parse_failure=1,verdict='INCORRECT' WHERE key='mmlu_pro:31'")
    with pytest.raises(ValueError, match='fails pilot'):
        validate(arm_db)
