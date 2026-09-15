/** Run inside the mount namespace and retain actual child exit/signal identity. */
import * as fs from 'node:fs';
import { spawn } from 'node:child_process';

const [statusPath, binary, ...args] = process.argv.slice(2);
if (!statusPath || !binary) throw new Error('missing compiler process observer arguments');
const child = spawn(binary, args, { stdio: 'inherit' });
child.once('error', error => {
  fs.writeFileSync(statusPath, JSON.stringify({ error: error.message }));
  process.exitCode = 1;
});
child.once('exit', (code, signal) => {
  fs.writeFileSync(statusPath, JSON.stringify({ code, signal }));
});
