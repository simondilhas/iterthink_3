# Vendored JavaScript (offline, no build step)

| file | package | version | license |
|---|---|---|---|
| htmx-2.0.11.min.js | htmx.org | 2.0.11 | 0BSD |
| htmx-ext-sse-2.2.4.js | htmx-ext-sse | 2.2.4 | 0BSD |
| three/build/three.module.js | three | 0.186.1 | MIT |
| three/build/three.core.js | three | 0.186.1 | MIT |
| three/examples/jsm/loaders/GLTFLoader.js | three | 0.186.1 | MIT |
| three/examples/jsm/controls/OrbitControls.js | three | 0.186.1 | MIT |
| three/examples/jsm/utils/BufferGeometryUtils.js | three | 0.186.1 | MIT |
| three/examples/jsm/utils/SkeletonUtils.js | three | 0.186.1 | MIT |

Three.js files keep the upstream layout and are unmodified, so the loaders'
relative imports resolve. A page that uses them declares the import map:

```html
<script type="importmap">
{"imports": {"three": "/static/vendor/three/build/three.module.js",
             "three/addons/": "/static/vendor/three/examples/jsm/"}}
</script>
```

Add a row for every vendored file.
Update THIRD_PARTY_NOTICES.md when adding a file.
