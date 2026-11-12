#!/usr/bin/env node
/**
 * Static sanity checks for the frontend:
 *  1. every relative import resolves to a file that exists
 *  2. every local <script>/<link> referenced by an HTML page exists
 *  3. every element id / form field name a page module touches exists in that page
 *
 * Run: node scripts/check_frontend.mjs
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const FRONTEND = join(ROOT, 'frontend');
const problems = [];

function walk(dir, filter) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full, filter));
    else if (filter(full)) out.push(full);
  }
  return out;
}

function relativePath(file) {
  return relative(ROOT, file);
}

// 1. module imports resolve -------------------------------------------------
const modules = walk(join(FRONTEND, 'js'), (file) => file.endsWith('.js'));
for (const file of modules) {
  const source = readFileSync(file, 'utf8');
  const importPattern = /(?:^|\n)\s*(?:import|export)[^'"\n]*from\s*['"](\.[^'"]+)['"]/g;
  let match;
  while ((match = importPattern.exec(source)) !== null) {
    const target = resolve(dirname(file), match[1]);
    try {
      statSync(target);
    } catch {
      problems.push(`${relativePath(file)}: import '${match[1]}' does not resolve to a file`);
    }
  }
}

// 1b. every imported name is actually exported --------------------------------
function exportedNames(source) {
  const names = new Set();
  for (const match of source.matchAll(/export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)/g)) {
    names.add(match[1]);
  }
  for (const match of source.matchAll(/export\s*\{([^}]*)\}/g)) {
    match[1].split(',').forEach((entry) => {
      const parts = entry.split(/\s+as\s+/);
      const name = (parts[1] || parts[0] || '').trim();
      if (name) names.add(name);
    });
  }
  return names;
}

for (const file of modules) {
  const source = readFileSync(file, 'utf8');
  const importPattern = /import\s*\{([^}]*)\}\s*from\s*['"](\.[^'"]+)['"]/g;
  let match;
  while ((match = importPattern.exec(source)) !== null) {
    const target = resolve(dirname(file), match[2]);
    let targetSource;
    try {
      targetSource = readFileSync(target, 'utf8');
    } catch {
      continue; // already reported by the import-resolution check
    }
    const available = exportedNames(targetSource);
    for (const entry of match[1].split(',')) {
      const name = entry.split(/\s+as\s+/)[0].trim();
      if (!name) continue;
      if (!available.has(name)) {
        problems.push(`${relativePath(file)}: imports '${name}' which ${match[2]} does not export`);
      }
    }
  }
}

// 2. HTML asset references exist --------------------------------------------
const pages = [join(FRONTEND, 'index.html'), ...walk(join(FRONTEND, 'pages'), (file) => file.endsWith('.html'))];
for (const page of pages) {
  const source = readFileSync(page, 'utf8');
  const refPattern = /(?:src|href)\s*=\s*"(\/[^"]+)"/g;
  let match;
  while ((match = refPattern.exec(source)) !== null) {
    const url = match[1];
    if (url.startsWith('//')) continue;
    const folder = url.startsWith('/assets/') ? 'assets'
      : url.startsWith('/js/') ? 'js'
        : url.startsWith('/vendor/') ? 'vendor'
          : null;
    if (!folder) continue;
    const target = join(FRONTEND, folder, url.slice(folder.length + 2));
    try {
      statSync(target);
    } catch {
      problems.push(`${relativePath(page)}: references '${url}' which does not exist`);
    }
  }
}

// 3. page modules only touch elements that exist in their page --------------
const idPattern = /getElementById\(\s*['"]([^'"]+)['"]\s*\)/g;
const namePattern = /namedItem\(\s*['"]([^'"]+)['"]\s*\)/g;
const selectNamePattern = /querySelector(?:All)?\(\s*['"]\[name=['"]([^'"]+)['"]\]['"]\s*\)/g;

for (const page of pages) {
  const source = readFileSync(page, 'utf8');
  const moduleMatch = source.match(/<script[^>]+type="module"[^>]+src="\/js\/([^"]+\.js)"/);
  if (!moduleMatch) {
    problems.push(`${relativePath(page)}: no ES module script is referenced`);
    continue;
  }
  const moduleFile = join(FRONTEND, 'js', moduleMatch[1]);
  const moduleSource = readFileSync(moduleFile, 'utf8');
  const htmlIds = new Set([...source.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
  const htmlNames = new Set([...source.matchAll(/\bname="([^"]+)"/g)].map((m) => m[1]));

  const checkIds = new Set();
  let match;
  while ((match = idPattern.exec(moduleSource)) !== null) checkIds.add(match[1]);
  while ((match = selectNamePattern.exec(moduleSource)) !== null) {
    if (!htmlNames.has(match[1])) {
      problems.push(`${relativePath(moduleFile)}: form field '${match[1]}' is missing from ${relativePath(page)}`);
    }
  }
  while ((match = namePattern.exec(moduleSource)) !== null) {
    if (!htmlNames.has(match[1])) {
      problems.push(`${relativePath(moduleFile)}: form field '${match[1]}' is missing from ${relativePath(page)}`);
    }
  }
  for (const id of checkIds) {
    if (!htmlIds.has(id)) {
      problems.push(`${relativePath(moduleFile)}: element id '${id}' is missing from ${relativePath(page)}`);
    }
  }
}

if (problems.length) {
  console.error('Frontend checks failed:');
  problems.forEach((problem) => console.error(`  - ${problem}`));
  process.exit(1);
}
console.log(`Frontend checks passed: ${modules.length} modules, ${pages.length} pages, all references resolve.`);
