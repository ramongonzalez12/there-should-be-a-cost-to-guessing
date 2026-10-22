
(function () {
  var bar = document.getElementById('scrollprogress');
  if (bar) {
    function update() {
      var y = window.scrollY || document.documentElement.scrollTop;
      var h = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (h > 0 ? Math.min(100, (y / h) * 100) : 0) + '%';
    }
    addEventListener('scroll', update, { passive: true });
    addEventListener('resize', update);
    update();
  }

  // Fade whichever edge of a horizontal scroller actually has content hidden
  // behind it, and neither edge when the content fits. Applied to every
  // horizontal scroller with a hidden scrollbar (nav row, section rail, table
  // wrappers, chart scroller), because the cue means the same thing in all of
  // them and an unconditional fade would be a claim about hidden content that
  // is false most of the time.
  function fades(el) {
    var max = el.scrollWidth - el.clientWidth;
    // Cap the ramp near the actual overflow: a table hanging 8px over its box
    // deserves an 8px whisper, not a 26px bite out of its last readable column.
    var w = max > 1 ? Math.min(26, max + 6) + 'px' : '0px';
    el.style.setProperty('--fade-start', el.scrollLeft > 1 ? w : '0px');
    el.style.setProperty('--fade-end', el.scrollLeft < max - 1 ? w : '0px');
  }
  var scrollers = document.querySelectorAll(
    '.scroll-nav-links, .section-nav-links, .table-wrap, .cal-chart-scroll');
  function allFades() { scrollers.forEach(fades); }
  scrollers.forEach(function (el) {
    el.addEventListener('scroll', function () { fades(el); }, { passive: true });
  });
  addEventListener('resize', allFades);

  var row = document.querySelector('.scroll-nav-links');
  if (!row) { allFades(); return; }

  // Bring the current page's link into view. On a phone the row is wider than
  // the screen, so the marked link can sit off the right edge — leaving the one
  // page the reader is actually on as the only one with no indicator. Set
  // scrollLeft directly rather than calling scrollIntoView, which would also
  // scroll the document and land the reader partway down the article.
  //
  // Measured from bounding rects rather than offsetLeft. The row is not a
  // positioned element, so offsetLeft is relative to the fixed bar and silently
  // includes the wordmark's width, which biases every comparison by however
  // wide "Below Zero" happens to render.
  var here = row.querySelector('.here');
  // Must clear the 26px fade ramp with room to spare, or the reveal parks the
  // current page's link inside the fade and the one marked link in the row
  // renders dimmest. 16px looked fine while desktop had no fade to clear.
  var pad = 34;
  function reveal() {
    if (!here) return;
    var h = here.getBoundingClientRect(), r = row.getBoundingClientRect();
    var delta = 0;
    if (h.right + pad > r.right) delta = h.right + pad - r.right;
    else if (h.left - pad < r.left) delta = h.left - pad - r.left;
    if (delta) row.scrollLeft += delta;
    fades(row);
  }
  reveal();

  // Re-reveal on resize. Rotating a phone to landscape fits the whole row, and
  // rotating back re-lays it out scrolled to the left, which drops the marker
  // off the right edge again. The fade handler already runs here; without the
  // marker running too, a rotate leaves the reader on the one page the bar does
  // not indicate.
  addEventListener('resize', reveal);

  // And once webfonts land. This script runs at parse time, so it measures the
  // row in the fallback face; when Inter arrives the links re-flow and the
  // scroll position computed against the old metrics no longer frames the
  // marker. Cheap to redo, and on a fast connection it is a no-op.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(reveal);

  allFades();
})();
(function () {
  var rail = document.querySelector('.section-nav');
  if (!rail) return;
  var links = Array.prototype.slice.call(
    rail.querySelectorAll('.section-nav-links a')
  );
  var pairs = links.map(function (link) {
    return { link: link, heading: document.getElementById(link.hash.slice(1)) };
  }).filter(function (pair) { return pair.heading; });

  function updateSection() {
    /* Keep this comfortably below the 112px anchor landing line. Reusing the
       same boundary makes the active section depend on sub-pixel rounding. */
    var threshold = rail.getBoundingClientRect().bottom + 28;
    var active = null;
    pairs.forEach(function (pair) {
      if (pair.heading.getBoundingClientRect().top <= threshold) active = pair;
    });
    pairs.forEach(function (pair) {
      var current = pair === active;
      pair.link.classList.toggle('here', current);
      if (current) pair.link.setAttribute('aria-current', 'location');
      else pair.link.removeAttribute('aria-current');
    });
  }

  addEventListener('scroll', updateSection, { passive: true });
  addEventListener('resize', updateSection);
  updateSection();
})();

// Calibration scatters are wider than a phone. Their data sit in the
// top-right (high accuracy, high confidence), so a scroller that opens at
// scrollLeft 0 shows the empty left of the plot and three stray points
// (Sep 2 sweep: 5 of 83 marks visible). Open each scroller at its right
// edge; the reader can still scroll back to the origin.
(function () {
  function openAtData() {
    document.querySelectorAll('.cal-chart-scroll').forEach(function (el) {
      var max = el.scrollWidth - el.clientWidth;
      if (max > 1 && el.scrollLeft < 1) el.scrollLeft = max;
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', openAtData);
  } else {
    openAtData();
  }
})();
