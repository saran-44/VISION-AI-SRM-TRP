# Vendored frontend dependencies

Third-party browser bundles are vendored here so the application can run from a
single origin (and so the Content-Security-Policy can stay on `script-src 'self'`).
Pinned versions:

| File | Library | Version | Source | License |
| --- | --- | --- | --- | --- |
| `chart.umd.js` | Chart.js | 4.4.4 | npm `chart.js@4.4.4` (`dist/chart.umd.js`) | MIT — see `licenses/chart.js-4.4.4-LICENSE.md` |
| `hls.min.js` | hls.js | 1.5.17 | npm `hls.js@1.5.17` (`dist/hls.min.js`) | BSD-3-Clause — see `licenses/hls.js-1.5.17-LICENSE` |
| `xlsx.full.min.js` | SheetJS (`xlsx`) | 0.18.5 | npm `xlsx@0.18.5` (`dist/xlsx.full.min.js`) | Apache-2.0 — see `licenses/xlsx-0.18.5-LICENSE` |

SheetJS publishes newer releases on its own CDN (`https://cdn.sheetjs.com`); the npm
package `xlsx@0.18.5` is the newest version available on the public npm registry and
is the version pinned here. To upgrade, replace the file and update this table plus
`licenses/`.

These files are generated artifacts — do not hand-edit them. To refresh them:

```bash
npm pack chart.js@4.4.4 hls.js@1.5.17 xlsx@0.18.5
tar -xzf chart.js-4.4.4.tgz && cp package/dist/chart.umd.js frontend/vendor/chart.umd.js
```
