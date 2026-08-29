"""The one renderer, as a page this package generates rather than ships.

Generated rather than served from ``assets/index.html`` for a reason worth
stating plainly: an asset under a package is one every adopter's wheel has to
remember to include, and the version of this dashboard that read one shipped
without it — so every request to ``/`` raised ``FileNotFoundError`` and the
sub-app had to be retired downstream. A page built from the declarations
cannot be left out of a build.

There is one script and it draws whatever :mod:`lup.devtools.dashboard.wizard`
describes: a scope selector, then a card per step, each with its guide, its
external link, its form or its rows, and whatever live check and undo the step
declares. It knows no step by name, so a project adding one writes a
declaration and nothing here changes.

Two conventions the engine defines and this honours. A step the server marks
un-offered is drawn with its reason and no form, so the page never offers what
a request would then be refused for. And a row carrying a ``stream`` path opens
a socket against it and paints the frames it sends — the shape a flow takes
when what somebody has to do happens in a browser the server is holding.
"""

# lup: ignore[constant-declaration] — the renderer itself, one file with no
# build step so that serving it needs nothing but this process
WIZARD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup</title>
<style>
  :root { --line: #e3e3e0; --dim: #666; --ok: #16794a; --bad: #a3331f; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0 auto; max-width: 54rem;
         padding: 2rem 1rem 6rem; color: #1a1a1a; background: #fdfdfc; }
  h1 { font-size: 1.5rem; margin: 0 0 .3rem; }
  p.lede { color: var(--dim); margin: 0 0 1.5rem; }
  .scopes{ display: flex; gap: .5rem; flex-wrap: wrap; align-items: center;
            border-bottom: 1px solid var(--line); padding-bottom: 1rem;
            margin-bottom: 1.5rem; }
  .scopes.tab { font: inherit; padding: .3rem .8rem; cursor: pointer;
                 border: 1px solid var(--line); background: #fff; border-radius: 4px; }
  .scopes.tab.on { border-color: #1a1a1a; font-weight: 600; }
  .step { border: 1px solid var(--line); border-radius: 6px; padding: 1rem 1.2rem;
          margin: 0 0 1rem; background: #fff; }
  .step h2 { font-size: 1.05rem; margin: 0; display: flex; gap: .6rem;
             align-items: baseline; }
  .mark { font-size: .9rem; }
  .mark.done { color: var(--ok); }
  .detail { color: var(--dim); font-size: .9rem; font-weight: 400; margin-left: auto; }
  .blurb { color: #444; margin: .5rem 0; }
  ol.guide { color: #444; margin: .5rem 0; padding-left: 1.3rem; }
  ol.guide li { margin: .25rem 0; }
  .guide-lines { color: #444; margin: .5rem 0; }
  .guide-lines p { margin: .2rem 0; }
  .blocked { color: var(--dim); font-style: italic; margin: .5rem 0 0; }
  label { display: block; margin: .6rem 0 .2rem; font-size: .9rem; color: #333; }
  input { font: inherit; padding: .3rem .45rem; width: 100%; max-width: 34rem;
          border: 1px solid var(--line); border-radius: 4px; box-sizing: border-box; }
  button { font: inherit; padding: .3rem .8rem; cursor: pointer; border-radius: 4px;
           border: 1px solid var(--line); background: #fff; }
  button.go { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
  .row { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap;
         padding: .45rem 0; border-top: 1px solid #f0f0ee; }
  .row .name { font-weight: 600; min-width: 9rem; }
  .row .state { color: var(--dim); flex: 1; min-width: 12rem; }
  .actions { margin-top: .8rem; display: flex; gap: .5rem; flex-wrap: wrap; }
  .ext { display: inline-block; margin: .4rem 0; }
  #screen { border: 1px solid #ccc; max-width: 100%; display: none; margin-top: 1rem; }
  #status { position: sticky; bottom: 0; background: #fdfdfc; padding: .7rem 0;
            border-top: 1px solid var(--line); color: #333; }
  .ok { color: var(--ok); }
  .bad { color: var(--bad); }
  .notice { background: #fffbe6; border: 1px solid #f0e2a8; padding: .8rem 1rem;
            border-radius: 6px; margin-bottom: 1rem; }
</style>
</head>
<body>
<h1 id="title">Setup</h1>
<p class="lede" id="lede"></p>
<div class="scopes" id="scopes"></div>
<div id="notice"></div>
<div id="steps"></div>
<canvas id="screen" width="1280" height="800" tabindex="0"></canvas>
<div id="status"></div>
<script>
const el = (id) => document.getElementById(id);
let scope = new URLSearchParams(location.search).get('scope') || '';

function say(text, ok) {
  const s = el('status');
  s.textContent = text || '';
  s.className = ok === undefined ? '' : (ok ? 'ok' : 'bad');
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(body === undefined ? {} : body),
  });
  return res.json();
}

const q = () => '?scope=' + encodeURIComponent(scope);

async function refresh() {
  draw(await (await fetch('/api/wizard' + q())).json());
}

// Every reply carries the page as it stands afterwards, so nothing here
// renders from what it assumed happened.
function applied(reply) {
  say(reply.outcome.message, reply.outcome.ok);
  scope = reply.view.chosen || scope;
  draw(reply.view);
}

function field(f) {
  const wrap = document.createElement('div');
  const label = document.createElement('label');
  label.textContent = f.label;
  const input = document.createElement('input');
  input.type = f.secret ? 'password' : 'text';
  input.placeholder = f.placeholder || '';
  input.dataset.key = f.key;
  wrap.append(label, input);
  return wrap;
}

function answersOf(node) {
  return {answers: [...node.querySelectorAll('input[data-key]')].map(
    (i) => ({key: i.dataset.key, value: i.value}))};
}

function rowNode(step, row) {
  const li = document.createElement('div');
  li.className = 'row';
  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = row.name;
  const state = document.createElement('span');
  state.className = 'state';
  state.textContent = row.detail;
  li.append(name, state);
  for (const act of row.acts) {
    const b = document.createElement('button');
    b.textContent = act.label;
    b.title = act.consequence;
    b.onclick = () => act.slug === 'sign-in'
      ? startLogin(row)
      : ask(li, step, row, act);
    li.append(b);
  }
  return li;
}

// An act that asks for a value grows its input in place, so what is being
// confirmed stays visible beside the prompt.
function ask(li, step, row, act) {
  if (!act.asks) return runAct(step, row, act, '');
  const box = document.createElement('span');
  const input = document.createElement('input');
  input.placeholder = act.asks;
  input.style.maxWidth = act.destructive ? '12rem' : '24rem';
  const go = document.createElement('button');
  go.textContent = act.destructive ? 'Confirm' : 'Save';
  go.onclick = () => runAct(step, row, act, input.value);
  input.onkeydown = (e) => { if (e.key === 'Enter') go.click(); };
  box.append(input, go);
  li.append(box);
  input.focus();
}

async function runAct(step, row, act, answer) {
  say('Working…');
  applied(await post(`/api/wizard/${step.slug}/act` + q(),
                     {row: row.name, act: act.slug, answer}));
}

function stepNode(step) {
  const box = document.createElement('section');
  box.className = 'step';

  const h = document.createElement('h2');
  const mark = document.createElement('span');
  mark.className = 'mark' + (step.standing.done ? ' done' : '');
  mark.textContent = step.standing.done ? '✓' : '○';
  const title = document.createElement('span');
  title.textContent = step.title;
  const detail = document.createElement('span');
  detail.className = 'detail';
  detail.textContent = step.standing.detail || '';
  h.append(mark, title, detail);
  box.append(h);

  if (step.blurb) {
    const p = document.createElement('p');
    p.className = 'blurb';
    p.textContent = step.blurb;
    box.append(p);
  }
  // Prose written for a terminal usually numbers itself, so a step says
  // whether its guide wants numbering rather than getting it regardless.
  if (step.guide.length) {
    const list = document.createElement(step.numbered ? 'ol' : 'div');
    list.className = step.numbered ? 'guide' : 'guide-lines';
    for (const line of step.guide) {
      const item = document.createElement(step.numbered ? 'li' : 'p');
      item.textContent = line;
      list.append(item);
    }
    box.append(list);
  }
  if (step.opens) {
    const a = document.createElement('a');
    a.className = 'ext';
    a.href = step.opens;
    a.target = '_blank';
    a.rel = 'noreferrer';
    a.textContent = 'Open that page →';
    box.append(a);
  }

  if (step.kind === 'rows') {
    for (const row of step.rows) box.append(rowNode(step, row));
  }

  // A step the server withholds is drawn with its reason and no form, so the
  // page cannot offer something a request would then be refused for.
  if (!step.standing.offered) {
    if (step.standing.blocked) {
      const p = document.createElement('p');
      p.className = 'blocked';
      p.textContent = step.standing.blocked;
      box.append(p);
    }
  } else if (step.fields.length) {
    const form = document.createElement('div');
    for (const f of step.fields) form.append(field(f));
    const go = document.createElement('button');
    go.className = 'go';
    go.textContent = step.submit || 'Save';
    go.onclick = async () => {
      say('Working…');
      applied(await post(`/api/wizard/${step.slug}/run` + q(), answersOf(form)));
    };
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.append(go);
    form.append(actions);
    box.append(form);
  }

  const extra = document.createElement('div');
  extra.className = 'actions';
  if (step.tests) {
    const t = document.createElement('button');
    t.textContent = step.tests;
    t.onclick = async () => {
      say('Checking…');
      applied(await post(`/api/wizard/${step.slug}/test` + q()));
    };
    extra.append(t);
  }
  if (step.undoes) {
    const r = document.createElement('button');
    r.textContent = step.undoes;
    r.onclick = async () => {
      say('Clearing…');
      applied(await post(`/api/wizard/${step.slug}/reset` + q()));
    };
    extra.append(r);
  }
  if (extra.children.length) box.append(extra);
  return box;
}

// The selector is drawn only where there is a choice to make, and the create
// affordance only where the project declared a label for it — a deployment
// with one scope it did not name should see neither.
function drawScopes(viewData) {
  const bar = el('scopes');
  bar.innerHTML = '';
  if (viewData.scopes.length > 1 || viewData.creates) {
    const label = document.createElement('span');
    label.textContent = (viewData.scope_label || 'Scope') + ':';
    bar.append(label);
  }
  for (const s of viewData.scopes) {
    const b = document.createElement('button');
    b.className = 'tab' + (s.chosen ? ' on' : '');
    b.textContent = s.label;
    b.title = s.detail;
    b.onclick = () => { scope = s.name; refresh(); };
    bar.append(b);
  }
  if (!viewData.creates) return;
  const input = document.createElement('input');
  input.placeholder = viewData.create_asks || 'Name';
  input.style.maxWidth = '11rem';
  const add = document.createElement('button');
  add.textContent = viewData.creates;
  add.onclick = async () => {
    say('Making…');
    applied(await post('/api/scopes', {name: input.value.trim()}));
  };
  input.onkeydown = (e) => { if (e.key === 'Enter') add.click(); };
  bar.append(input, add);
}

function draw(viewData) {
  el('title').textContent = viewData.title;
  document.title = viewData.title;
  el('lede').textContent = viewData.lede;
  drawScopes(viewData);
  el('notice').innerHTML = '';
  if (viewData.notice) {
    const n = document.createElement('div');
    n.className = 'notice';
    n.textContent = viewData.notice;
    el('notice').append(n);
  }
  const steps = el('steps');
  steps.innerHTML = '';
  for (const step of viewData.steps) steps.append(stepNode(step));
}

// Signing in is the one act performed differently here: the terminal opens a
// browser where it runs, and this streams the same window over a socket to
// whoever is reading. Same act, two mechanisms — so the button comes from the
// row like every other, and only where it goes differs.
function startLogin(row) {
  const screen = el('screen');
  const ctx = screen.getContext('2d');
  say('Starting a browser…');
  screen.style.display = 'block';
  screen.focus();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${proto}://${location.host}${row.stream}`);
  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.error) { say('Error: ' + msg.error, false); return; }
    if (msg.signed_in) {
      say('Signed in. You can enrol them now.', true);
      screen.style.display = 'none';
      socket.close();
      refresh();
      return;
    }
    const img = new Image();
    img.onload = () => ctx.drawImage(img, 0, 0, screen.width, screen.height);
    img.src = 'data:image/jpeg;base64,' + msg.frame;
    say('Sign in below.');
  };
  socket.onclose = () => { screen.style.display = 'none'; };

  const at = (e) => {
    const box = screen.getBoundingClientRect();
    return {
      x: (e.clientX - box.left) * (screen.width / box.width),
      y: (e.clientY - box.top) * (screen.height / box.height),
    };
  };
  const send = (payload) => {
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  };
  screen.onmousedown = (e) => {
    const p = at(e);
    send({mouse: {action: 'mousePressed', x: p.x, y: p.y}});
  };
  screen.onmouseup = (e) => {
    const p = at(e);
    send({mouse: {action: 'mouseReleased', x: p.x, y: p.y}});
  };
  screen.onmousemove = (e) => {
    const p = at(e);
    send({mouse: {action: 'mouseMoved', x: p.x, y: p.y, button: 'none'}});
  };
  screen.onwheel = (e) => {
    e.preventDefault();
    const p = at(e);
    send({wheel: {x: p.x, y: p.y, delta_x: e.deltaX, delta_y: e.deltaY}});
  };
  screen.onkeydown = (e) => {
    e.preventDefault();
    const text = e.key.length === 1 ? e.key : '';
    send({key: {action: text ? 'keyDown' : 'rawKeyDown', key: e.key,
                code: e.code, text: text}});
  };
  screen.onkeyup = (e) => {
    e.preventDefault();
    send({key: {action: 'keyUp', key: e.key, code: e.code}});
  };
}

refresh();
</script>
</body>
</html>
"""
