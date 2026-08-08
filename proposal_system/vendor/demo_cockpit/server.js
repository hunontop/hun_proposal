// 제안 자동화 시연 콕핏 — 로컬 러너
// [실행] 버튼 → run_all.bat 를 부모 폴더에서 실행 → 출력을 SSE로 콕핏에 스트리밍.
// 실행: node server.js  →  http://localhost:5700
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const PORT = 5700;
const ROOT = __dirname;                 // 콕핏 UI 위치 (이 파일이 있는 폴더)
// 원본 시연 콕핏 스냅샷. 실무용 실행은 proposal_system/cockpit/server.js를 사용한다.
// 아래 탐색 로직은 원본 보존용이며, 독립 실행 경로의 기준은 vendor/proposal_core다.
function findPipeline(start) {
  let dir = start;
  for (let i = 0; i < 8; i++) {
    const cand = path.join(dir, '제안업무자동화');
    if (fs.existsSync(path.join(cand, 'run_all.bat'))) return cand;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(__dirname, '..', 'proposal_core');
}
const PIPELINE = findPipeline(ROOT);

http.createServer((req, res) => {
  if (req.url === '/' || req.url.startsWith('/index')) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(fs.readFileSync(path.join(ROOT, 'index.html')));
    return;
  }
  if (req.url === '/run') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });
    const send = (type, data) => res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    const bat = path.join(PIPELINE, 'run_all.bat');
    // draft PPTX 출력은 이 콕핏 폴더의 draft/ 로(상대경로) — 원본 파이프라인 폴더를 안 건드림.
    const OUT_DIR = path.join(ROOT, 'draft');
    fs.mkdirSync(OUT_DIR, { recursive: true });
    send('line', '> ' + bat);
    send('line', '> draft → ' + OUT_DIR);
    // 절대경로를 인자 배열로 (조합 문자열의 cmd 따옴표 문제 회피). chcp/PYTHONUTF8은 bat 내부 처리.
    // DRAFT_OUT_DIR 는 make_pptx.py 가 읽어 출력 위치를 이 폴더로 돌린다.
    const child = spawn('cmd.exe', ['/c', bat, 'nopause'], { cwd: PIPELINE, env: { ...process.env, DRAFT_OUT_DIR: OUT_DIR } });
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    const feed = (str) => String(str).split(/\r?\n/).forEach(l => { if (l.trim()) send('line', l); });
    child.stdout.on('data', feed);
    child.stderr.on('data', feed);
    child.on('error', e => { send('line', '[러너 오류] ' + e.message); send('done', { code: -1 }); res.end(); });
    child.on('close', code => { send('done', { code }); res.end(); });
    req.on('close', () => { try { child.kill(); } catch (_) {} });
    return;
  }
  if (req.url.startsWith('/search')) {
    const m = req.url.match(/[?&]keyword=([^&]*)/);
    const kw = m ? decodeURIComponent(m[1]).trim() : '';
    const args = kw ? ['collector.py', kw, '--json'] : ['collector.py', '--json'];
    const child = spawn('python', args, { cwd: PIPELINE, env: { ...process.env, PYTHONUTF8: '1' } });
    let out = '', err = '';
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', d => out += d);
    child.stderr.on('data', d => err += d);
    child.on('error', e => { res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: e.message })); });
    child.on('close', code => {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      const line = out.trim().split(/\r?\n/).filter(Boolean).pop() || '';   // 마지막 비어있지 않은 줄 = JSON
      res.end(line || JSON.stringify({ error: 'no output', code, stderr: err.slice(-400) }));
    });
    return;
  }
  if (req.url.startsWith('/analyze')) {
    const m = req.url.match(/[?&]bidNo=([^&]*)/);
    const bidNo = m ? decodeURIComponent(m[1]).trim() : '';
    if (!bidNo) { res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: 'bidNo 없음' })); return; }
    const child = spawn('python', ['analyzer.py', bidNo], { cwd: PIPELINE, env: { ...process.env, PYTHONUTF8: '1' } });
    let err = '';
    child.stderr.setEncoding('utf8'); child.stderr.on('data', d => err += d);
    child.on('error', e => { res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: e.message })); });
    child.on('close', code => {
      const safe = bidNo.replace(/\//g, '_');
      const pf = path.join(PIPELINE, 'analysis', safe + '_프롬프트.txt');
      fs.readFile(pf, 'utf8', (e, txt) => {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        if (e) res.end(JSON.stringify({ error: '프롬프트 생성 실패 (공고를 찾지 못했거나 첨부 처리 오류)', code, stderr: err.slice(-500) }));
        else res.end(JSON.stringify({ bidNo, prompt: txt }));
      });
    });
    return;
  }
  res.writeHead(404); res.end('not found');
}).listen(PORT, () => {
  console.log('제안 자동화 시연 콕핏 → http://localhost:' + PORT);
  console.log('(부모 폴더의 run_all.bat 를 실행합니다. python·의존성 설치 환경 필요)');
});
