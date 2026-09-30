/** Use the installed harness runtime, never the newer source checkout. */
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.env.KC_DSH_RUNTIME_ROOT || join(process.env.APPDATA, 'npm/node_modules/@deepseek-ai/dsh');
const require = createRequire(join(root, 'package.json'));
if (require('./package.json').version !== '0.1.5-rc.2') throw new Error('Revalidate recovery integration for this harness version');
export const runtime = name => import(pathToFileURL(require.resolve(`@deepseek-ai/${name}`)).href);
