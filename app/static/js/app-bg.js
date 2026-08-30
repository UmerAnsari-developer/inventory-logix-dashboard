// Futuristic Holographic 3D Background — Full App
// Toroidal grid + particle field + hexagonal plane + scanning lines
// Matches InventoryLogix design tokens (sky-blue accent, dark surface)

import * as THREE from 'three';

const canvas = document.getElementById('appScene');
if (!canvas) throw new Error('No #appScene canvas');

const root = document.documentElement;
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ── Theme Tokens ────────────────────────────────────────────────
const THEMES = {
  dark: {
    bg: 0x04070f,
    fog: 0x04070f,
    fogDensity: 0.035,
    accent: 0x38bdf8,
    accentHex: '#38bdf8',
    accent2: 0x818cf8,
    success: 0x22c55e,
    danger: 0xf87171,
    grid: 0x0c2d4a,
    particle: 0x7dd3fc,
    scanLine: '#38bdf8',
    hexFill: 0x0a1628,
    hexEdge: 0x1a3a5c,
  },
  light: {
    bg: 0xf0f4fa,
    fog: 0xf0f4fa,
    fogDensity: 0.02,
    accent: 0x0ea5e9,
    accentHex: '#0ea5e9',
    accent2: 0x6366f1,
    success: 0x16a34a,
    danger: 0xdc2626,
    grid: 0xc8daf0,
    particle: 0x38bdf8,
    scanLine: '#0ea5e9',
    hexFill: 0xe8f0fc,
    hexEdge: 0xb0c4de,
  }
};

function getThemeName() {
  return root.getAttribute('data-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}
function T() { return THEMES[getThemeName()]; }

// ── Renderer ────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(canvas.clientWidth, canvas.clientHeight);
renderer.setClearColor(T().bg, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(T().fog, T().fogDensity);

const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.1, 250);
camera.position.set(0, 12, 20);
camera.lookAt(0, 0, 0);

// ── Lighting ────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.25));

const keyLight = new THREE.DirectionalLight(0xffffff, 0.4);
keyLight.position.set(5, 15, 8);
scene.add(keyLight);

const accentLight = new THREE.PointLight(T().accent, 0.6, 40);
accentLight.position.set(-8, 6, 0);
scene.add(accentLight);

const accentLight2 = new THREE.PointLight(T().accent2, 0.3, 35);
accentLight2.position.set(8, 4, -6);
scene.add(accentLight2);

// ── Hexagonal Ground Grid ───────────────────────────────────────
function createHexGrid(radius, spacing, color) {
  const group = new THREE.Group();
  const hexShape = new THREE.Shape();
  const s = spacing * 0.48;
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 6;
    const x = s * Math.cos(angle);
    const y = s * Math.sin(angle);
    if (i === 0) hexShape.moveTo(x, y);
    else hexShape.lineTo(x, y);
  }
  hexShape.closePath();

  const edgeGeo = new THREE.EdgesGeometry(new THREE.ShapeGeometry(hexShape));
  const edgeMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.15 });

  const filledMat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0.03, side: THREE.DoubleSide
  });
  const filledGeo = new THREE.ShapeGeometry(hexShape);

  const sqrt3 = Math.sqrt(3);
  for (let q = -radius; q <= radius; q++) {
    for (let r = -radius; r <= radius; r++) {
      if (Math.abs(q + r) > radius) continue;
      const x = spacing * (sqrt3 * q + sqrt3 / 2 * r);
      const z = spacing * (3 / 2 * r);
      const dist = Math.sqrt(x * x + z * z);
      if (dist > radius * spacing) continue;

      const fill = new THREE.Mesh(filledGeo, filledMat);
      fill.rotation.x = -Math.PI / 2;
      fill.position.set(x, -0.01, z);
      group.add(fill);

      const edge = new THREE.LineSegments(edgeGeo, edgeMat);
      edge.rotation.x = -Math.PI / 2;
      edge.position.set(x, 0, z);
      group.add(edge);
    }
  }
  return group;
}

const hexGrid = createHexGrid(8, 2.2, T().hexEdge);
scene.add(hexGrid);

// ── Toroidal Ring (holographic) ─────────────────────────────────
function createTorus(radius, tube, segments, color) {
  const geo = new THREE.TorusGeometry(radius, tube, 8, segments);
  const edges = new THREE.EdgesGeometry(geo);
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.2 });
  return new THREE.LineSegments(edges, mat);
}

const torus1 = createTorus(7, 0.08, 64, T().accent);
torus1.rotation.x = Math.PI / 2;
torus1.position.y = 3;
scene.add(torus1);

const torus2 = createTorus(5.5, 0.05, 48, T().accent2);
torus2.rotation.x = Math.PI / 2;
torus2.position.y = 5;
scene.add(torus2);

const torus3 = createTorus(9, 0.04, 80, T().accent);
torus3.rotation.x = Math.PI / 2;
torus3.position.y = 1.5;
scene.add(torus3);

// ── Floating Holographic Panels ─────────────────────────────────
const panelGroup = new THREE.Group();
scene.add(panelGroup);

function createHoloPanel(w, h, color, opacity) {
  const geo = new THREE.PlaneGeometry(w, h);
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity, side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending, depthWrite: false
  });
  const mesh = new THREE.Mesh(geo, mat);

  // Edge border
  const edgeGeo = new THREE.EdgesGeometry(geo);
  const edgeMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: opacity * 3 });
  const edge = new THREE.LineSegments(edgeGeo, edgeMat);
  mesh.add(edge);

  return mesh;
}

const holoPanels = [
  { w: 2.5, h: 1.5, x: -6, y: 5, z: -3, ry: 0.3 },
  { w: 2, h: 1.2, x: 5, y: 6, z: -2, ry: -0.25 },
  { w: 3, h: 1.8, x: 0, y: 7, z: -5, ry: 0.1 },
  { w: 1.8, h: 1, x: -4, y: 4, z: 2, ry: -0.4 },
  { w: 2.2, h: 1.3, x: 6, y: 3.5, z: 1, ry: 0.35 },
];

holoPanels.forEach(p => {
  const panel = createHoloPanel(p.w, p.h, T().accent, 0.06);
  panel.position.set(p.x, p.y, p.z);
  panel.rotation.y = p.ry;
  panelGroup.add(panel);
});

// ── Vertical Light Pillars ──────────────────────────────────────
const pillarGroup = new THREE.Group();
scene.add(pillarGroup);

const pillarPositions = [
  { x: -7, z: -4 }, { x: 7, z: -3 }, { x: -3, z: 5 },
  { x: 4, z: 4 }, { x: 0, z: -6 }, { x: -5, z: 0 }, { x: 6, z: 1 }
];

pillarPositions.forEach(p => {
  const geo = new THREE.CylinderGeometry(0.02, 0.02, 12, 6);
  const mat = new THREE.MeshBasicMaterial({
    color: T().accent, transparent: true, opacity: 0.08,
    blending: THREE.AdditiveBlending, depthWrite: false
  });
  const pillar = new THREE.Mesh(geo, mat);
  pillar.position.set(p.x, 6, p.z);
  pillarGroup.add(pillar);
});

// ── Particle Field (3 layers: near, mid, far) ───────────────────
const LAYER_COUNTS = [80, 150, 60];
const LAYER_RANGES = [[0, 10], [10, 30], [30, 60]];
const layers = [];

LAYER_COUNTS.forEach((count, li) => {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  const cols = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const vel = new Float32Array(count * 3);
  const range = LAYER_RANGES[li];

  const accentC = new THREE.Color(T().accent);
  const accent2C = new THREE.Color(T().accent2);
  const successC = new THREE.Color(T().success);
  const palette = [accentC, accentC, accentC, accent2C, successC];

  for (let i = 0; i < count; i++) {
    const i3 = i * 3;
    const angle = Math.random() * Math.PI * 2;
    const dist = range[0] + Math.random() * (range[1] - range[0]);
    pos[i3] = Math.cos(angle) * dist;
    pos[i3 + 1] = Math.random() * 15 - 2;
    pos[i3 + 2] = Math.sin(angle) * dist;

    vel[i3] = (Math.random() - 0.5) * 0.008;
    vel[i3 + 1] = (Math.random() - 0.5) * 0.004;
    vel[i3 + 2] = (Math.random() - 0.5) * 0.008;

    const c = palette[Math.floor(Math.random() * palette.length)];
    cols[i3] = c.r; cols[i3 + 1] = c.g; cols[i3 + 2] = c.b;

    sizes[i] = li === 0 ? 2.5 : li === 1 ? 1.8 : 1.2;
  }

  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(cols, 3));
  geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

  const mat = new THREE.PointsMaterial({
    size: li === 0 ? 0.12 : li === 1 ? 0.08 : 0.05,
    vertexColors: true, transparent: true,
    opacity: li === 0 ? 0.8 : li === 1 ? 0.5 : 0.25,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  const points = new THREE.Points(geo, mat);
  scene.add(points);
  layers.push({ points, geo, vel, count });
});

// ── Scanning Line Ring ──────────────────────────────────────────
const scanGeo = new THREE.RingGeometry(0.3, 0.35, 64);
const scanMat = new THREE.MeshBasicMaterial({
  color: T().accent, transparent: true, opacity: 0.15,
  side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false
});
const scanRing = new THREE.Mesh(scanGeo, scanMat);
scanRing.rotation.x = Math.PI / 2;
scanRing.position.y = 0.1;
scene.add(scanRing);

// ── Orbiting Data Nodes ─────────────────────────────────────────
const nodeGroup = new THREE.Group();
scene.add(nodeGroup);

const nodeGeo = new THREE.OctahedronGeometry(0.15, 0);
const nodes = [];

for (let i = 0; i < 12; i++) {
  const mat = new THREE.MeshBasicMaterial({
    color: [T().accent, T().accent2, T().success][i % 3],
    transparent: true, opacity: 0.5,
    wireframe: i % 3 === 0,
  });
  const node = new THREE.Mesh(nodeGeo, mat);
  const orbit = 3 + Math.random() * 5;
  const speed = 0.2 + Math.random() * 0.3;
  const phase = Math.random() * Math.PI * 2;
  const yPos = 2 + Math.random() * 6;
  node.position.set(Math.cos(phase) * orbit, yPos, Math.sin(phase) * orbit);
  nodeGroup.add(node);
  nodes.push({ mesh: node, orbit, speed, phase, yPos });
}

// ── Connection Lines (neural network) ───────────────────────────
const connectionGroup = new THREE.Group();
scene.add(connectionGroup);

function rebuildConnections() {
  while (connectionGroup.children.length) connectionGroup.remove(connectionGroup.children[0]);
  const maxDist = 8;
  const nodePositions = nodes.map(n => n.mesh.position);
  for (let i = 0; i < nodePositions.length; i++) {
    for (let j = i + 1; j < nodePositions.length; j++) {
      const d = nodePositions[i].distanceTo(nodePositions[j]);
      if (d > maxDist) continue;
      const pts = [nodePositions[i].clone(), nodePositions[j].clone()];
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const mat = new THREE.LineBasicMaterial({
        color: T().accent, transparent: true,
        opacity: 0.08 * (1 - d / maxDist),
        blending: THREE.AdditiveBlending,
      });
      connectionGroup.add(new THREE.Line(geo, mat));
    }
  }
}

// ── Mouse Parallax ──────────────────────────────────────────────
let mx = 0, my = 0, tx = 0, ty = 0;
canvas.addEventListener('mousemove', e => {
  const r = canvas.getBoundingClientRect();
  mx = ((e.clientX - r.left) / r.width - 0.5) * 2;
  my = ((e.clientY - r.top) / r.height - 0.5) * 2;
});

// ── Theme Switch ────────────────────────────────────────────────
function applyTheme() {
  const t = T();
  renderer.setClearColor(t.bg, 1);
  scene.fog.color.set(t.fog);
  accentLight.color.set(t.accent);
  accentLight2.color.set(t.accent2);

  // Update torus colors
  torus1.material.color.set(t.accent);
  torus2.material.color.set(t.accent2);
  torus3.material.color.set(t.accent);

  // Update scan ring
  scanMat.color.set(t.accent);

  // Update hex grid
  hexGrid.children.forEach(c => {
    if (c.material) c.material.color.set(t.hexEdge);
  });

  // Update particles
  const ac = new THREE.Color(t.accent);
  const ac2 = new THREE.Color(t.accent2);
  const sc = new THREE.Color(t.success);
  const pal = [ac, ac, ac, ac2, sc];
  layers.forEach(layer => {
    const colAttr = layer.geo.getAttribute('color');
    for (let i = 0; i < layer.count; i++) {
      const c = pal[Math.floor(Math.random() * pal.length)];
      colAttr.setXYZ(i, c.r, c.g, c.b);
    }
    colAttr.needsUpdate = true;
  });

  // Update nodes
  nodes.forEach((n, i) => {
    n.mesh.material.color.set([t.accent, t.accent2, t.success][i % 3]);
  });

  rebuildConnections();
}

const observer = new MutationObserver(applyTheme);
observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });

// ── Animation Loop ──────────────────────────────────────────────
const clock = new THREE.Clock();
let frameCount = 0;

function tick() {
  requestAnimationFrame(tick);
  const dt = clock.getDelta();
  const t = clock.getElapsedTime();
  frameCount++;

  // Smooth camera parallax
  tx += (mx * 2 - tx) * 0.025;
  ty += (my * 1 - ty) * 0.025;
  camera.position.x = tx;
  camera.position.y = 12 - ty * 0.5;
  camera.lookAt(0, 2, 0);

  // Torus rotation
  torus1.rotation.z = t * 0.08;
  torus2.rotation.z = -t * 0.06;
  torus3.rotation.z = t * 0.04;

  // Torus bob
  torus1.position.y = 3 + Math.sin(t * 0.3) * 0.3;
  torus2.position.y = 5 + Math.sin(t * 0.25 + 1) * 0.2;
  torus3.position.y = 1.5 + Math.sin(t * 0.2 + 2) * 0.15;

  // Hex grid subtle pulse
  hexGrid.children.forEach((c, i) => {
    if (c.material && c.material.opacity !== undefined) {
      c.material.opacity = 0.03 + Math.sin(t * 0.5 + i * 0.1) * 0.01;
    }
  });

  // Holographic panels float
  panelGroup.children.forEach((p, i) => {
    p.position.y += Math.sin(t * 0.4 + i * 0.8) * 0.002;
    p.material.opacity = 0.04 + Math.sin(t * 0.6 + i) * 0.02;
  });

  // Light pillars pulse
  pillarGroup.children.forEach((p, i) => {
    p.material.opacity = 0.05 + Math.sin(t * 0.8 + i * 0.5) * 0.03;
  });

  // Scan ring expand + reset
  const scanScale = 1 + (t % 4) * 2.5;
  scanRing.scale.set(scanScale, scanScale, 1);
  scanMat.opacity = 0.12 * (1 - (t % 4) / 4);

  // Orbiting nodes
  nodes.forEach(n => {
    const angle = t * n.speed + n.phase;
    n.mesh.position.x = Math.cos(angle) * n.orbit;
    n.mesh.position.z = Math.sin(angle) * n.orbit;
    n.mesh.position.y = n.yPos + Math.sin(t * 0.5 + n.phase) * 0.3;
    n.mesh.rotation.x += 0.02;
    n.mesh.rotation.y += 0.015;
  });

  // Rebuild connections every 60 frames
  if (frameCount % 60 === 0) rebuildConnections();

  // Particle drift
  layers.forEach(layer => {
    const posAttr = layer.geo.getAttribute('position');
    for (let i = 0; i < layer.count; i++) {
      const i3 = i * 3;
      posAttr.array[i3] += layer.vel[i3];
      posAttr.array[i3 + 1] += Math.sin(t * 0.3 + i * 0.05) * 0.002;
      posAttr.array[i3 + 2] += layer.vel[i3 + 2];

      const dist = Math.sqrt(
        posAttr.array[i3] ** 2 + posAttr.array[i3 + 2] ** 2
      );
      if (dist > LAYER_RANGES[layers.indexOf(layer)][1] + 10) {
        const angle = Math.random() * Math.PI * 2;
        const d = LAYER_RANGES[layers.indexOf(layer)][0];
        posAttr.array[i3] = Math.cos(angle) * d;
        posAttr.array[i3 + 2] = Math.sin(angle) * d;
      }
      if (posAttr.array[i3 + 1] > 16) posAttr.array[i3 + 1] = -2;
      if (posAttr.array[i3 + 1] < -3) posAttr.array[i3 + 1] = 14;
    }
    posAttr.needsUpdate = true;
  });

  // Accent light orbit
  accentLight.position.x = Math.sin(t * 0.15) * 10;
  accentLight.position.z = Math.cos(t * 0.15) * 10;
  accentLight2.position.x = Math.cos(t * 0.12) * 8;
  accentLight2.position.z = Math.sin(t * 0.12) * 8;

  renderer.render(scene, camera);
}

// ── Resize ──────────────────────────────────────────────────────
function onResize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', onResize);

// ── Reduced Motion ──────────────────────────────────────────────
if (RM) {
  renderer.render(scene, camera);
} else {
  tick();
}
