/* InventoryLogix — Landing 3D background: particle constellation, midnight terminal */
(function () {
  'use strict';

  function init() {
    var canvas = document.getElementById('landingBg');
    if (!canvas || typeof THREE === 'undefined') return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.z = 10;

    function isDark() { return document.documentElement.getAttribute('data-theme') !== 'dark'; }
    // Midnight terminal palette: cyan primary, lime accent, warm amber tertiary
    var ACCENT = 0x22d3ee;   // cyan
    var ACCENT2 = 0xa3e635;  // lime
    var ACCENT3 = 0xfbbf24;  // amber

    var N = 180;
    var pts = [];
    var positions = new Float32Array(N * 3);
    var vels = [];
    var colors = new Float32Array(N * 3);
    var palette = [new THREE.Color(ACCENT), new THREE.Color(ACCENT2), new THREE.Color(ACCENT3)];

    for (var i = 0; i < N; i++) {
      var x = (Math.random() - 0.5) * 24;
      var y = (Math.random() - 0.5) * 14;
      var z = (Math.random() - 0.5) * 10;
      positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z;
      pts.push({ x: x, y: y, z: z });
      vels.push({
        x: (Math.random() - 0.5) * 0.012,
        y: (Math.random() - 0.5) * 0.010,
        z: (Math.random() - 0.5) * 0.008
      });
      var c = palette[i % 3];
      colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
    }

    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    var pointMat = new THREE.PointsMaterial({
      size: 0.09,
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    var points = new THREE.Points(geo, pointMat);
    scene.add(points);

    // Constellation lines
    var lineGeo = new THREE.BufferGeometry();
    var MAX_SEG = N * 8;
    var linePos = new Float32Array(MAX_SEG * 6);
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePos, 3));
    var lineMat = new THREE.LineBasicMaterial({
      color: ACCENT,
      transparent: true,
      opacity: 0.14,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    var lines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(lines);

    // A few glowing core nodes (larger points)
    var coreGeo = new THREE.BufferGeometry();
    var CORE = 12, corePos = new Float32Array(CORE * 3);
    for (var k = 0; k < CORE; k++) {
      corePos[k * 3] = (Math.random() - 0.5) * 16;
      corePos[k * 3 + 1] = (Math.random() - 0.5) * 9;
      corePos[k * 3 + 2] = (Math.random() - 0.5) * 5;
    }
    coreGeo.setAttribute('position', new THREE.BufferAttribute(corePos, 3));
    var coreMat = new THREE.PointsMaterial({
      size: 0.28, color: ACCENT2, transparent: true, opacity: 0.9,
      blending: THREE.AdditiveBlending, depthWrite: false
    });
    scene.add(new THREE.Points(coreGeo, coreMat));

    // Mouse parallax
    var mx = 0, my = 0;
    window.addEventListener('mousemove', function (e) {
      mx = (e.clientX / window.innerWidth - 0.5) * 2;
      my = (e.clientY / window.innerHeight - 0.5) * 2;
    }, { passive: true });

    window.addEventListener('resize', function () {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    var LINK = 2.4; // link distance

    function frame() {
      var p = geo.attributes.position.array;
      for (var i = 0; i < N; i++) {
        pts[i].x += vels[i].x; pts[i].y += vels[i].y; pts[i].z += vels[i].z;
        if (pts[i].x > 12 || pts[i].x < -12) vels[i].x *= -1;
        if (pts[i].y > 7 || pts[i].y < -7) vels[i].y *= -1;
        if (pts[i].z > 5 || pts[i].z < -5) vels[i].z *= -1;
        p[i * 3] = pts[i].x; p[i * 3 + 1] = pts[i].y; p[i * 3 + 2] = pts[i].z;
      }
      geo.attributes.position.needsUpdate = true;

      // Rebuild line segments
      var seg = 0;
      var lp = lineGeo.attributes.position.array;
      for (var a = 0; a < N && seg < MAX_SEG; a++) {
        for (var b = a + 1; b < N && seg < MAX_SEG; b++) {
          var dx = pts[a].x - pts[b].x, dy = pts[a].y - pts[b].y, dz = pts[a].z - pts[b].z;
          if (dx * dx + dy * dy + dz * dz < LINK * LINK) {
            var o = seg * 6;
            lp[o] = pts[a].x; lp[o + 1] = pts[a].y; lp[o + 2] = pts[a].z;
            lp[o + 3] = pts[b].x; lp[o + 4] = pts[b].y; lp[o + 5] = pts[b].z;
            seg++;
          }
        }
      }
      lineGeo.setDrawRange(0, seg * 2);
      lineGeo.attributes.position.needsUpdate = true;

      // Parallax
      scene.rotation.y += (mx * 0.18 - scene.rotation.y) * 0.03;
      scene.rotation.x += (my * 0.10 - scene.rotation.x) * 0.03;

      renderer.render(scene, camera);
      requestAnimationFrame(frame);
    }
    frame();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();