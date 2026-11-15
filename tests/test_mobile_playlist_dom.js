// Run the real PLAYLIST_NEXT_JS against minimal, deterministic mobile DOM fixtures.
// No external packages, live network requests, or browser accounts required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const py = fs.readFileSync('playlist_navigation.py', 'utf8');
const match = py.match(/PLAYLIST_NEXT_JS = r"""([\s\S]*?)"""/);
assert.ok(match, 'Playlist navigation script exists');

function scenario({current = 'alone', names = ['too-late', 'hardest'], position = '1 / 618', roots = true, index = null}) {
  const rows = names.map((id, i) => {
    const anchor = {
      id, chosen: false,
      matches: query => query.startsWith('a['),
      getAttribute: key => key === 'href' ? '/watch?v=' + id : null,
      setAttribute: (key, value) => { if (key === 'data-trickster-next-target') anchor.chosen = value === '1'; },
      querySelector: () => null
    };
    const row = {
      anchor, matches: () => false, querySelector: query => query.startsWith('a[') ? anchor : null,
      getAttribute: key => key === 'data-index' && index ? String(index[i]) : null
    };
    return row;
  });
  const root = {
    innerText: 'Clean songs ' + position,
    querySelectorAll: query => query.includes('ytm-playlist-panel-video-renderer') ? rows : []
  };
  const document = {
    querySelector: () => null,
    querySelectorAll: () => roots ? [root] : []
  };
  const context = {document, location: {href: 'https://m.youtube.com/watch?v=' + current + '&list=PLTEST'}, URL};
  const run = vm.runInNewContext('(' + match[1] + ')', context);
  const outcome = run();
  return {outcome: JSON.parse(JSON.stringify(outcome)), rows};
}

let s = scenario({});
assert.equal(s.outcome.found, true);
assert.equal(s.outcome.method, 'first row following playlist item 1');
assert.equal(s.rows[0].anchor.chosen, true);
assert.equal(s.rows[1].anchor.chosen, false);

s = scenario({names: ['alone', 'too-late', 'hardest'], position: '1 / 618'});
assert.equal(s.outcome.found, true);
assert.equal(s.rows[1].anchor.chosen, true);

s = scenario({names: ['song-9', 'song-10'], position: '8 / 618', index: [9, 10]});
assert.equal(s.outcome.found, true);
assert.equal(s.rows[0].anchor.chosen, true);

s = scenario({names: ['other-song', 'another'], position: '8 / 618'});
assert.equal(s.outcome.found, false);
assert.ok(s.rows.every(row => !row.anchor.chosen));

s = scenario({roots: false});
assert.equal(s.outcome.found, false);
console.log('PASS mobile playlist DOM fallbacks and ambiguity safeguards');
