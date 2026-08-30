// Shared Three.js background for all pages
// Initializes the animated wave + particle background with dynamic theme support

import * as THREE from 'three';
const canvas = document.getElementById('scene');
const dimEl  = document.getElementById('dim');
const root   = document.documentElement;
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const isLanding = !!document.getElementById('hero');

// ============================================================
// THEME CONFIGURATION
// ============================================================
const THEMES = {
  light: {
    bg: 0xf0f4fa,
    fog: 0xf0f4fa,
    fogDensity: 0.025,
    waveColA: '#2d5a8a',
    waveColB: '#4a90d9',
    waveScanGlow: '#3a7bd5',
    particleColor: 0x3a7bd5,
    lineColor: 0x5a9fd4,
    glow1: 'rgba(58, 123, 213, .5)',
    glow2: 'rgba(74, 110, 241, .42)',
    glow3: 'rgba(120, 90, 247, .3)',
    horizon: 'rgba(74, 144, 217, .55)',
    dustColor: 0x5a9fd4,
    dimColor: '#f0f4fa',
  },
  dark: {
    bg: 0x04070f,
    fog: 0x04070f,
    fogDensity: 0.038,
    waveColA: '#1e3a5f',
    waveColB: '#67e8f9',
    waveScanGlow: '#12a5e9',
    particleColor: 0x9bd9ff,
    lineColor: 0x5eead4,
    glow1: 'rgba(14,165,233,.5)',
    glow2: 'rgba(99,102,241,.42)',
    glow3: 'rgba(168,85,247,.3)',
    horizon: 'rgba(125,211,252,.65)',
    dustColor: 0x8fd6ff,
    dimColor: '#04070f',
  }
};

function getCurrentTheme() {
  return document.documentElement.getAttribute('data-theme') || 
         (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function getTheme() {
  return THEMES[getCurrentTheme()];
}

// ============================================================
// ADAPTIVE INK — sample scene luminance → retune text color
// ============================================================
function applyInk(L, S) {
  const eff = L * (1 - S) * (1 - S * .35);
  const t = THREE.MathUtils.clamp((eff - .42) * 2.4, 0, 1);
  const ch = [
    Math.round(238 + (10 - 238) * t),
    Math.round(242 + (16 - 242) * t),
    Math.round(251 + (38 - 251) * t)
  ];
  root.style.setProperty('--ink', ch.join(' '));
  root.style.setProperty('--scrim-o', S.toFixed(3));
  // Only auto-toggle ink-dark if NOT using manual theme
  if (!document.documentElement.hasAttribute('data-theme') || !localStorage.getItem('theme')) {
    document.body.classList.toggle('ink-dark', t > .5);
  }
}

function sampleLuminance(renderer) {
  try {
    const lc = document.createElement('canvas'); lc.width = lc.height = 48;
    const lctx = lc.getContext('2d', { willReadFrequently: true });
    lctx.drawImage(renderer.domElement, 0, 0, 48, 48);
    const d = lctx.getImageData(0, 0, 48, 48).data;
    let s = 0;
    for (let i = 0; i < d.length; i += 16) {
      s += .2126 * d[i] + .7152 * d[i+1] + .0722 * d[i+2];
    }
    return s / (d.length / 16) / 255;
  } catch { return null; }
}

if (!canvas) {
  console.warn('Three.js background: canvas#scene not found');
} else {
  let sceneOK = false;
  let lum = .12, scrim = 0;

  // Scene objects that need theme updates
  let scene, renderer, waves, waveUniforms, net, lines, glows, horizon, dust;
  
  // Theme transition state
  let themeTransition = { active: false, progress: 0, startTheme: null, targetTheme: null, startTime: 0 };
  const THEME_TRANSITION_DURATION = 800; // ms

  try { sceneOK = initScene(); } catch (err) { 
    canvas.style.display = 'none'; 
    console.warn('WebGL off:', err); 
    applyInk(0.10, 0.30);
  }

  function initScene() {
    const theme = getTheme();
    
    renderer = new THREE.WebGLRenderer({
      canvas, antialias: true, powerPreference: 'high-performance',
      preserveDrawingBuffer: true
    });
    const dpr = () => Math.min(devicePixelRatio, innerWidth < 768 ? 1.5 : 2);
    renderer.setPixelRatio(dpr());
    renderer.setSize(innerWidth, innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(theme.bg);
    scene.fog = new THREE.FogExp2(theme.fog, theme.fogDensity);

    const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, .1, 100);
    camera.position.set(0, 2.6, 10.5);
    camera.lookAt(0, 1.1, 0);

    waveUniforms = {
      uTime:   { value: 0 },
      uAmp:    { value: 1.15 },
      uScan:   { value: -30 },
      uOp:     { value: .5 },
      uColA:   { value: new THREE.Color(theme.waveColA) },
      uColB:   { value: new THREE.Color(theme.waveColB) }
    };
    const waveMat = new THREE.ShaderMaterial({
      uniforms: waveUniforms, transparent: true, wireframe: true, depthWrite: false,
      vertexShader: `
        uniform float uTime; uniform float uAmp; uniform float uScan;
        varying float vElev; varying float vFade; varying float vScanGlow; varying float vX;
        void main(){
          vec3 p = position;
          float e =
            sin(p.x * .22 + uTime * .55) * 1.0 +
            sin(p.y * .28 - uTime * .42) * .7 +
            sin((p.x + p.y) * .11 + uTime * .3) * 1.5 +
            sin(length(p.xy) * .35 - uTime * .25) * .4;
          p.z += e * uAmp;
          vElev = e;
          vX = p.x;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vFade = 1.0 - smoothstep(10.0, 34.0, -mv.z);
          vScanGlow = 1.0 - smoothstep(0.0, 2.6, abs(p.x - uScan));
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform vec3 uColA; uniform vec3 uColB; uniform float uOp;
        varying float vElev; varying float vFade; varying float vScanGlow; varying float vX;
        void main(){
          float t = clamp(vElev * .32 + .5, 0.0, 1.0);
          vec3 col = mix(uColA, uColB, t);
          col += vec3(.18, .5, .6) * vScanGlow * .55;
          float edge = 1.0 - smoothstep(16.0, 30.0, abs(vX));
          gl_FragColor = vec4(col, uOp * vFade * edge);
        }`
    });
    const waveGeo = new THREE.PlaneGeometry(64, 60, innerWidth < 768 ? 72 : 110, innerWidth < 768 ? 72 : 110);
    waves = new THREE.Mesh(waveGeo, waveMat);
    waves.rotation.x = -Math.PI / 2;
    waves.position.set(0, -2.6, -6);
    scene.add(waves);

    const spriteTex = (() => {
      const c = document.createElement('canvas'); c.width = c.height = 64;
      const g = c.getContext('2d');
      const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, 'rgba(255,255,255,1)');
      gr.addColorStop(.35, 'rgba(180,225,255,.6)');
      gr.addColorStop(1, 'rgba(180,225,255,0)');
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
      return new THREE.CanvasTexture(c);
    })();

    const CN = innerWidth < 768 ? 44 : 64;
    const nodes = [];
    for (let i = 0; i < CN; i++) {
      nodes.push({
        x: (Math.random() - .5) * 22,
        y: 1.2 + Math.random() * 6.5,
        z: (Math.random() - .5) * 8 - 1.5,
        p1: Math.random() * 6.28, p2: Math.random() * 6.28,
        s1: .14 + Math.random() * .2, s2: .1 + Math.random() * .16
      });
    }
    const nPos = new Float32Array(CN * 3);
    const nGeo = new THREE.BufferGeometry();
    nGeo.setAttribute('position', new THREE.BufferAttribute(nPos, 3));
    net = new THREE.Points(nGeo, new THREE.PointsMaterial({
      map: spriteTex, color: theme.particleColor, size: .34, transparent: true, opacity: .85,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
    }));
    scene.add(net);

    const MAXSEG = 200;
    const lPos = new Float32Array(MAXSEG * 6);
    const lGeo = new THREE.BufferGeometry();
    lGeo.setAttribute('position', new THREE.BufferAttribute(lPos, 3));
    lines = new THREE.LineSegments(lGeo, new THREE.LineBasicMaterial({
      color: theme.lineColor, transparent: true, opacity: .16,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    scene.add(lines);

    const glowTex = hex => {
      const c = document.createElement('canvas'); c.width = c.height = 256;
      const g = c.getContext('2d');
      const gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
      gr.addColorStop(0, hex); gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
      return new THREE.CanvasTexture(c);
    };
    
    function createGlow(hex, x, y, z, s) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(s, s),
        new THREE.MeshBasicMaterial({ map: glowTex(hex), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
      m.position.set(x, y, z); scene.add(m); return m;
    }

    glows = [
      { m: createGlow(theme.glow1, -6, 3.2, -9, 22), ph: 0,   sp: .07 },
      { m: createGlow(theme.glow2, 5.5, 2.2, -10, 26), ph: 2.3, sp: .09 },
      { m: createGlow(theme.glow3, .5, -1, -8, 18),  ph: 4.6, sp: .11 },
    ];

    horizon = new THREE.Mesh(new THREE.PlaneGeometry(70, 1.4),
      new THREE.MeshBasicMaterial({ map: glowTex(theme.horizon), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
    horizon.position.set(0, -1.6, -14);
    scene.add(horizon);

    const DN = innerWidth < 768 ? 260 : 420;
    const dPos = new Float32Array(DN * 3), dSpd = new Float32Array(DN);
    for (let i = 0; i < DN; i++) {
      dPos[i*3] = (Math.random() - .5) * 26;
      dPos[i*3+1] = -3 + Math.random() * 12;
      dPos[i*3+2] = -8 + Math.random() * 12;
      dSpd[i] = .003 + Math.random() * .01;
    }
    const dGeo = new THREE.BufferGeometry();
    dGeo.setAttribute('position', new THREE.BufferAttribute(dPos, 3));
    dust = new THREE.Points(dGeo, new THREE.PointsMaterial({
      map: spriteTex, color: theme.dustColor, size: .1, transparent: true, opacity: .4,
      blending: THREE.AdditiveBlending, depthWrite: false
    }));
    scene.add(dust);

    let mx = 0, my = 0, scY = 0;
    addEventListener('pointermove', e => {
      mx = (e.clientX / innerWidth - .5) * 2;
      my = (e.clientY / innerHeight - .5) * 2;
    }, { passive: true });
    addEventListener('scroll', () => scY = scrollY, { passive: true });

    setInterval(() => { 
      if (sceneOK) {
        const sampled = sampleLuminance(renderer);
        if (sampled !== null) {
          lum += (sampled - lum) * .12;
          applyInk(lum, scrim);
        }
      }
    }, 400);

    const clock = new THREE.Clock();
    function frame() {
      const t = clock.getElapsedTime();

      const rawSp = Math.min(1, scY / Math.max(1, innerHeight * .9));
      const sp = isLanding ? rawSp : rawSp * .15;
      dimEl.style.opacity = (sp * .62).toFixed(3);
      renderer.toneMappingExposure = 1.2 - sp * .45;
      waveUniforms.uOp.value = .5 * (1 - sp * .72);
      net.material.opacity = .85 * (1 - sp * .7);
      lines.material.opacity = .16 * (1 - sp * .7);
      dust.material.opacity = .4 * (1 - sp * .7);
      glows.forEach(g => g.m.material.opacity = 1 - sp * .75);
      horizon.material.opacity = 1 - sp * .75;
      scrim = sp * .34;

      camera.position.x += (mx * .55 - camera.position.x) * .035;
      camera.position.y += ((2.6 - my * .28 + sp * 1.4) - camera.position.y) * .035;
      camera.lookAt(0, 1.1, 0);

      waveUniforms.uTime.value = t;
      waveUniforms.uScan.value = ((t * 4) % 56) - 28;
      waves.position.z = -6 + sp * 4;

      for (let i = 0; i < CN; i++) {
        const n = nodes[i];
        nPos[i*3]   = n.x + Math.sin(t * n.s1 + n.p1) * .9;
        nPos[i*3+1] = n.y + Math.sin(t * n.s2 + n.p2) * .5;
        nPos[i*3+2] = n.z + Math.cos(t * n.s1 * .7 + n.p2) * .6;
      }
      nGeo.attributes.position.needsUpdate = true;

      let seg = 0;
      const linkD2 = 2.4 * 2.4;
      outer:
      for (let i = 0; i < CN && seg < MAXSEG; i++) {
        for (let j = i + 1; j < CN; j++) {
          const dx = nPos[i*3]-nPos[j*3], dy = nPos[i*3+1]-nPos[j*3+1], dz = nPos[i*3+2]-nPos[j*3+2];
          if (dx*dx + dy*dy + dz*dz < linkD2) {
            lPos.set([nPos[i*3], nPos[i*3+1], nPos[i*3+2], nPos[j*3], nPos[j*3+1], nPos[j*3+2]], seg * 6);
            if (++seg >= MAXSEG) break outer;
          }
        }
      }
      lGeo.setDrawRange(0, seg * 2);
      lGeo.attributes.position.needsUpdate = true;

      glows.forEach(g => {
        g.m.position.x += (Math.sin(t * g.sp + g.ph) * 1.4 - g.m.position.x) * .015;
        g.m.position.y += (g.m.position.y * 0 + 2 + Math.cos(t * g.sp * .8 + g.ph) * .8 - g.m.position.y) * .015;
      });
      const dp = dGeo.attributes.position.array;
      for (let i = 0; i < DN; i++) { dp[i*3+1] += dSpd[i]; if (dp[i*3+1] > 9) dp[i*3+1] = -3; }
      dGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
      requestAnimationFrame(frame);
    }

    if (RM) {
      waveUniforms.uTime.value = 1.4; waveUniforms.uScan.value = 4;
      renderer.render(scene, camera);
      const sampled = sampleLuminance(renderer);
      if (sampled !== null) applyInk(sampled, 0);
    } else requestAnimationFrame(frame);

    addEventListener('resize', () => {
      renderer.setSize(innerWidth, innerHeight);
      renderer.setPixelRatio(dpr());
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      if (RM) renderer.render(scene, camera);
    });

    return true;
  }

  // ============================================================
  // DYNAMIC THEME SWITCHING
  // ============================================================
  function updateTheme() {
    if (!sceneOK) return;
    
    const theme = getTheme();
    
    // Update scene background & fog
    scene.background = new THREE.Color(theme.bg);
    scene.fog = new THREE.FogExp2(theme.fog, theme.fogDensity);
    
    // Update wave colors
    waveUniforms.uColA.value = new THREE.Color(theme.waveColA);
    waveUniforms.uColB.value = new THREE.Color(theme.waveColB);
    
    // Update particles
    net.material.color = new THREE.Color(theme.particleColor);
    
    // Update lines
    lines.material.color = new THREE.Color(theme.lineColor);
    
    // Update glows - recreate with new colors
    glows.forEach(g => scene.remove(g.m));
    const glowTex = hex => {
      const c = document.createElement('canvas'); c.width = c.height = 256;
      const g = c.getContext('2d');
      const gr = g.createRadialGradient(128, 128, 0, 128, 128, 128);
      gr.addColorStop(0, hex); gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
      return new THREE.CanvasTexture(c);
    };
    function createGlow(hex, x, y, z, s) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(s, s),
        new THREE.MeshBasicMaterial({ map: glowTex(hex), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
      m.position.set(x, y, z); scene.add(m); return m;
    }
    glows = [
      { m: createGlow(theme.glow1, -6, 3.2, -9, 22), ph: 0,   sp: .07 },
      { m: createGlow(theme.glow2, 5.5, 2.2, -10, 26), ph: 2.3, sp: .09 },
      { m: createGlow(theme.glow3, .5, -1, -8, 18),  ph: 4.6, sp: .11 },
    ];
    
    // Update horizon
    scene.remove(horizon);
    horizon = new THREE.Mesh(new THREE.PlaneGeometry(70, 1.4),
      new THREE.MeshBasicMaterial({ map: glowTex(theme.horizon), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
    horizon.position.set(0, -1.6, -14);
    scene.add(horizon);
    
    // Update dust
    dust.material.color = new THREE.Color(theme.dustColor);
    
    // Update dim element color
    dimEl.style.background = theme.dimColor;
  }

  // Listen for theme changes
  const themeObserver = new MutationObserver(() => {
    updateTheme();
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  // Also listen for storage changes (cross-tab sync)
  window.addEventListener('storage', (e) => {
    if (e.key === 'theme') updateTheme();
  });

  // Reveal animation for elements with [data-anim] or .reveal
  document.addEventListener('DOMContentLoaded', () => {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in', 'in-view', 'loaded');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });
    document.querySelectorAll('.reveal, [data-anim]').forEach(el => observer.observe(el));
  });
}

export {};