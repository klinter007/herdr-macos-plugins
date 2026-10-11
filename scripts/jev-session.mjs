// One gateway instance for one launched agent; reuse the installed gateway package.
import { spawn } from 'node:child_process';
import { createConnection } from 'node:net';
import { createRequire } from 'node:module';
import { mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { pathToFileURL } from 'node:url';

function api(method, params) {
  return new Promise((resolve, reject) => {
    const socket = createConnection(process.env.HERDR_SOCKET_PATH);
    let data = '';
    socket.setTimeout(4000, () => socket.destroy(new Error('Herdr request timed out')));
    socket.on('error', reject);
    socket.on('connect', () => socket.write(JSON.stringify({id: 'jev-session', method, params}) + '\n'));
    socket.on('data', chunk => {
      data += chunk;
      if (data.length > 1024 * 1024) return socket.destroy(new Error('Herdr response too large'));
      if (!data.includes('\n')) return;
      socket.end();
      try {
        const reply = JSON.parse(data.split('\n')[0]);
        if (reply.error) reject(new Error(reply.error.message)); else resolve(reply.result);
      } catch (error) { reject(error); }
    });
  });
}

export async function runSession({spawnAgent = spawn} = {}) {
  const root = process.env.TOOLS_JEV_PACKAGE;
  const kind = process.env.TOOLS_JEV_AGENT;
  if (!root || !['codex', 'claude'].includes(kind)) throw new Error('Missing Jev agent/package');
  const load = file => import(pathToFileURL(`${root}/${file}`));
  const {loadEnv} = await load('bin/launcher.mjs');
  loadEnv();
  const spec = (await load('bin/clients.mjs'))[kind];
  const {createApp} = await load('dist/app.js');
  const {loadConfig} = await load('dist/config.js');
  const {createAskJev} = await load('dist/jev.js');
  const {createEventLog} = await load('dist/events.js');
  const require = createRequire(`${root}/package.json`);
  const {serve} = await import(pathToFileURL(require.resolve('@hono/node-server')));
  const env = {...process.env, HOST: '127.0.0.1', PORT: '0', JEV_CLIENT: kind,
    UPSTREAM_BASE_URL: spec.upstream(), JEV_ROUTING: 'off'};
  // Match the official launcher: the agent supplies its own provider credentials.
  for (const key of ['UPSTREAM_API_KEY', 'ROUTER_API_KEY', 'JEV_DEBUG_DUMP_DIR', 'JEV_LOG_FILE']) delete env[key];
  const config = loadConfig(env);
  if (!config.jevApiKey) throw new Error('No Jev provider key configured. Use jev-' + kind + ' --setup.');
  const events = createEventLog({capacity: 100});
  const name = kind === 'codex' ? 'Codex' : 'Claude';
  let model = 'model pending', lastLabel, labelsEnabled = true, busy = false;
  const app = createApp({config, askJev: createAskJev(config), events,
    log: entry => {
      if (entry.model && entry.model !== 'codex-auto-review') model = String(entry.model).replace(/[\x00-\x1f\x7f]/g, '').slice(0, 64);
    }});
  const server = serve({fetch: app.fetch, hostname: '127.0.0.1', port: 0});
  await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
  const port = server.address().port;
  const origin = `http://127.0.0.1:${port}`;
  const paneId = process.env.HERDR_PANE_ID;
  const record = process.env.TOOLS_JEV_RECORD;
  let child, timer;
  try {
    const pane = (await api('pane.get', {pane_id: paneId})).pane;
    mkdirSync(dirname(record), {recursive: true, mode: 0o700});
    writeFileSync(record + '.new', JSON.stringify({port, pid: process.pid, agent: kind,
      pane_id: paneId, terminal_id: pane.terminal_id, started_at: Date.now()}), {mode: 0o600});
    renameSync(record + '.new', record);
    const updateLabel = async () => {
      if (busy || !labelsEnabled) return;
      busy = true;
      try {
        const state = await (await fetch(origin + '/dashboard/events?since=999999999', {signal: AbortSignal.timeout(2000)})).json();
        const label = `${name} · ${model} · Jev ${state.router.routing ? 'On' : 'Off'}`;
        if (label !== lastLabel) {
          const current = (await api('pane.get', {pane_id: paneId})).pane;
          // Respect a label the user changes after our initial label.
          if (lastLabel && current.label !== lastLabel) { labelsEnabled = false; return; }
          await api('pane.rename', {pane_id: paneId, label});
          lastLabel = label;
        }
      } catch { /* The child still owns the gateway lifetime if Herdr is closing. */ }
      finally { busy = false; }
    };
    // The tab name stays short and fixed; the pane label carries model and state.
    await api('tab.rename', {tab_id: pane.tab_id, label: `${name} + Jev`}).catch(() => {});
    await updateLabel();
    timer = setInterval(updateLabel, 3000);
    console.log('Jev: Off for this agent session. Ctrl+B, then Shift+J opens its On/Off control.');
    child = spawnAgent(spec.client, spec.args?.(origin) ?? [], {
      cwd: process.env.TOOLS_JEV_CWD, stdio: 'inherit', env: {...process.env, ...spec.env?.(origin)},
    });
    const stop = () => { child.kill('SIGTERM'); setTimeout(() => child.kill('SIGKILL'), 3000).unref(); };
    for (const signal of ['SIGTERM', 'SIGHUP']) process.once(signal, stop);
    // Ctrl+C belongs to the interactive agent; the supervisor must stay alive.
    const ignoreInterrupt = () => {};
    process.on('SIGINT', ignoreInterrupt);
    try {
      return await new Promise((resolve, reject) => {
        child.once('error', reject);
        child.once('exit', code => resolve(code ?? 0));
      });
    } finally {
      process.off('SIGINT', ignoreInterrupt);
      for (const signal of ['SIGTERM', 'SIGHUP']) process.off(signal, stop);
    }
  } finally {
    clearInterval(timer);
    if (child && child.exitCode === null) child.kill('SIGTERM');
    server.closeAllConnections();
    server.close();
    rmSync(record, {force: true});
    rmSync(record + '.new', {force: true});
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { process.exitCode = await runSession(); }
  catch (error) { console.error('Jev session:', error.message); process.exitCode = 1; }
}
