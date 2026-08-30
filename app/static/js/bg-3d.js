/* =============================================================================
   InventoryLogix — 3D Ambient Cyber Matrix & Particle Space
   Interactive 3D Perspective Wireframe & Particle Constellation
   Enhanced with geometric shapes, grid floor, and mouse-reactive effects
   ============================================================================= */

(function () {
  'use strict';

  function init3DBackground() {
    const canvas = document.getElementById('bg3dCanvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let dpr = window.devicePixelRatio || 1;

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    }

    window.addEventListener('resize', resize);
    resize();

    // 3D Particles Configuration
    const NUM_PARTICLES = 80;
    const FOV = 500;
    const particles = [];

    // Color palette for particles
    const colors = [
      'rgba(16, 185, 129,',    // Emerald
      'rgba(14, 165, 233,',    // Sky blue
      'rgba(168, 85, 247,',    // Purple
      'rgba(245, 158, 11,',    // Amber
      'rgba(239, 68, 68,'      // Red
    ];

    for (let i = 0; i < NUM_PARTICLES; i++) {
      const colorIdx = Math.floor(Math.random() * colors.length);
      particles.push({
        x: (Math.random() - 0.5) * width * 2,
        y: (Math.random() - 0.5) * height * 2,
        z: Math.random() * 1000 + 50,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        vz: (Math.random() - 0.5) * 0.4,
        color: colors[colorIdx],
        size: Math.random() * 1.5 + 0.5,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.02,
        shape: Math.random() > 0.7 ? 'square' : 'circle',
        opacity: Math.random() * 0.5 + 0.3
      });
    }

    // Geometric shapes floating in background
    const geoShapes = [];
    const NUM_GEO_SHAPES = 15;
    for (let i = 0; i < NUM_GEO_SHAPES; i++) {
      geoShapes.push({
        x: (Math.random() - 0.5) * width * 1.5,
        y: (Math.random() - 0.5) * height * 1.5,
        z: Math.random() * 800 + 100,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.15,
        vz: (Math.random() - 0.5) * 0.2,
        size: Math.random() * 40 + 20,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.005,
        sides: [3, 4, 6, 8][Math.floor(Math.random() * 4)],
        color: colors[Math.floor(Math.random() * colors.length)],
        opacity: Math.random() * 0.15 + 0.05,
        wireframe: Math.random() > 0.5
      });
    }

    let targetRotX = 0;
    let targetRotY = 0;
    let rotX = 0;
    let rotY = 0;

    window.addEventListener('mousemove', function (e) {
      const cx = width / 2;
      const cy = height / 2;
      targetRotY = ((e.clientX - cx) / cx) * 0.2;
      targetRotX = ((e.clientY - cy) / cy) * 0.2;
    });

    // Mouse position for reactive effects
    let mouseX = width / 2;
    let mouseY = height / 2;
    window.addEventListener('mousemove', function(e) {
      mouseX = e.clientX;
      mouseY = e.clientY;
    });

    let isRunning = true;
    document.addEventListener('visibilitychange', function () {
      isRunning = !document.hidden;
      if (isRunning) requestAnimationFrame(render);
    });

    // 3D Perspective Grid at the bottom
    function draw3DGrid(cx, cy) {
      const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      if (!isDark) return;

      const gridY = height * 0.7;
      const lines = 16;
      const depthSteps = 15;
      const maxZ = 1000;

      ctx.save();
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.03)';
      ctx.lineWidth = 1;

      // Perspective horizontal grid lines
      for (let j = 1; j <= depthSteps; j++) {
        const z = (j / depthSteps) * maxZ;
        const scale = FOV / (FOV + z);
        const y = gridY + (height - gridY) * scale;
        const xSpan = (width * 0.95) * scale;

        ctx.beginPath();
        ctx.moveTo(cx - xSpan, y);
        ctx.lineTo(cx + xSpan, y);
        ctx.stroke();
      }

      // Converging perspective vertical grid lines
      for (let i = -lines / 2; i <= lines / 2; i++) {
        const xOffset = (i / (lines / 2)) * (width * 0.85);
        const zFar = maxZ;
        const scaleFar = FOV / (FOV + zFar);
        const xFar = cx + xOffset * scaleFar;
        const yFar = gridY;

        const scaleNear = FOV / (FOV + 10);
        const xNear = cx + xOffset * scaleNear * 1.5;
        const yNear = height;

        ctx.beginPath();
        ctx.moveTo(xFar, yFar);
        ctx.lineTo(xNear, yNear);
        ctx.stroke();
      }

      // Central glow line
      const gradient = ctx.createLinearGradient(cx, gridY, cx, height);
      gradient.addColorStop(0, 'rgba(16, 185, 129, 0.1)');
      gradient.addColorStop(1, 'rgba(16, 185, 129, 0)');
      ctx.strokeStyle = gradient;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, gridY);
      ctx.lineTo(cx, height);
      ctx.stroke();

      ctx.restore();
    }

    // Draw geometric shape
    function drawGeoShape(ctx, x, y, size, rotation, sides, color, opacity, wireframe) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(rotation);
      
      if (wireframe) {
        ctx.strokeStyle = color + opacity + ')';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const angle = (i / sides) * Math.PI * 2 - Math.PI / 2;
          const px = Math.cos(angle) * size;
          const py = Math.sin(angle) * size;
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.stroke();
      } else {
        ctx.fillStyle = color + (opacity * 0.5) + ')';
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const angle = (i / sides) * Math.PI * 2 - Math.PI / 2;
          const px = Math.cos(angle) * size;
          const py = Math.sin(angle) * size;
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
    }

    // Draw particle
    function drawParticle(ctx, x, y, size, rotation, color, opacity, shape) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(rotation);
      
      ctx.fillStyle = color + opacity + ')';
      ctx.beginPath();
      
      if (shape === 'square') {
        const halfSize = size * 0.7;
        ctx.rect(-halfSize, -halfSize, halfSize * 2, halfSize * 2);
      } else {
        ctx.arc(0, 0, size, 0, Math.PI * 2);
      }
      
      ctx.fill();
      
      // Inner glow
      if (opacity > 0.5) {
        ctx.shadowColor = color + '0.8)';
        ctx.shadowBlur = size * 3;
        if (shape === 'square') {
          const halfSize = size * 0.7;
          ctx.fillRect(-halfSize, -halfSize, halfSize * 2, halfSize * 2);
        } else {
          ctx.beginPath();
          ctx.arc(0, 0, size, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      
      ctx.restore();
    }

    function render() {
      if (!isRunning) return;

      ctx.clearRect(0, 0, width, height);

      const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      const cx = width / 2;
      const cy = height / 2;

      // Smooth camera rotation
      rotX += (targetRotX - rotX) * 0.04;
      rotY += (targetRotY - rotY) * 0.04;

      // Draw 3D grid floor
      draw3DGrid(cx, cy);

      const projected = [];

      // Project 3D Particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        p.x += p.vx;
        p.y += p.vy;
        p.z += p.vz;
        p.rotation += p.rotationSpeed;

        // Wrap around
        if (p.z < 20) p.z = 1000;
        if (p.z > 1100) p.z = 50;
        if (p.x < -width * 1.5) p.x = width * 1.5;
        if (p.x > width * 1.5) p.x = -width * 1.5;
        if (p.y < -height * 1.5) p.y = height * 1.5;
        if (p.y > height * 1.5) p.y = -height * 1.5;

        // 3D rotation transform
        const cosY = Math.cos(rotY);
        const sinY = Math.sin(rotY);
        const x1 = p.x * cosY + p.z * sinY;
        const z1 = -p.x * sinY + p.z * cosY;

        const cosX = Math.cos(rotX);
        const sinX = Math.sin(rotX);
        const y2 = p.y * cosX - z1 * sinX;
        const z2 = p.y * sinX + z1 * cosX;

        if (z2 + FOV <= 0) continue;

        const scale = FOV / (FOV + z2);
        const x2d = cx + x1 * scale;
        const y2d = cy + y2 * scale;
        const radius = Math.max(0.5, p.size * scale * 1.5);
        const alpha = isDark ? Math.min(p.opacity, Math.max(0.08, (1 - z2 / 1100) * p.opacity)) : Math.min(p.opacity * 0.3, Math.max(0.03, (1 - z2 / 1100) * p.opacity * 0.3));

        projected.push({ x: x2d, y: y2d, z: z2, alpha, color: p.color, radius, rotation: p.rotation, shape: p.shape });

        // Draw particle
        drawParticle(ctx, x2d, y2d, radius, p.rotation, p.color, alpha, p.shape);

        // Glowing node halo in dark mode
        if (isDark && alpha > 0.3) {
          ctx.beginPath();
          ctx.arc(x2d, y2d, radius * 3, 0, Math.PI * 2);
          ctx.fillStyle = p.color + (alpha * 0.15) + ')';
          ctx.fill();
        }
      }

      // Project and draw geometric shapes
      const projectedGeo = [];
      for (let i = 0; i < geoShapes.length; i++) {
        const g = geoShapes[i];

        g.x += g.vx;
        g.y += g.vy;
        g.z += g.vz;
        g.rotation += g.rotationSpeed;

        // Wrap around
        if (g.z < 50) g.z = 900;
        if (g.z > 950) g.z = 50;
        if (g.x < -width) g.x = width;
        if (g.x > width) g.x = -width;
        if (g.y < -height) g.y = height;
        if (g.y > height) g.y = -height;

        // 3D rotation transform
        const cosY = Math.cos(rotY);
        const sinY = Math.sin(rotY);
        const x1 = g.x * cosY + g.z * sinY;
        const z1 = -g.x * sinY + g.z * cosY;

        const cosX = Math.cos(rotX);
        const sinX = Math.sin(rotX);
        const y2 = g.y * cosX - z1 * sinX;
        const z2 = g.y * sinX + z1 * cosX;

        if (z2 + FOV <= 0) continue;

        const scale = FOV / (FOV + z2);
        const x2d = cx + x1 * scale;
        const y2d = cy + y2 * scale;
        const size = g.size * scale;
        const alpha = isDark ? g.opacity * scale * 0.8 : g.opacity * scale * 0.3;

        projectedGeo.push({ x: x2d, y: y2d, z: z2, alpha, color: g.color, size, rotation: g.rotation, sides: g.sides, wireframe: g.wireframe });

        // Draw geometric shape
        drawGeoShape(ctx, x2d, y2d, size, g.rotation, g.sides, g.color, alpha, g.wireframe);
      }

      // Draw 3D connection lines between nearby particles
      const maxDistance = isDark ? 140 : 100;
      for (let i = 0; i < projected.length; i++) {
        for (let j = i + 1; j < projected.length; j++) {
          const p1 = projected[i];
          const p2 = projected[j];
          const dx = p1.x - p2.x;
          const dy = p1.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < maxDistance) {
            const lineAlpha = (1 - dist / maxDistance) * (isDark ? 0.08 : 0.03);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = p1.color + lineAlpha + ')';
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // Draw connections between geo shapes and particles (mouse reactive)
      if (isDark) {
        for (let i = 0; i < projectedGeo.length; i++) {
          const g = projectedGeo[i];
          const dx = g.x - mouseX;
          const dy = g.y - mouseY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          
          if (dist < 300) {
            const alpha = (1 - dist / 300) * 0.05;
            ctx.beginPath();
            ctx.moveTo(g.x, g.y);
            ctx.lineTo(mouseX, mouseY);
            ctx.strokeStyle = g.color + alpha + ')';
            ctx.lineWidth = 0.5;
            ctx.setLineDash([5, 5]);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }
      }

      // Draw mouse-reactive ripple effect
      if (isDark) {
        const time = Date.now() * 0.001;
        const rippleRadius = 100 + Math.sin(time * 2) * 30;
        const gradient = ctx.createRadialGradient(mouseX, mouseY, 0, mouseX, mouseY, rippleRadius);
        gradient.addColorStop(0, 'rgba(16, 185, 129, 0.03)');
        gradient.addColorStop(0.5, 'rgba(14, 165, 233, 0.015)');
        gradient.addColorStop(1, 'rgba(16, 185, 129, 0)');
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(mouseX, mouseY, rippleRadius, 0, Math.PI * 2);
        ctx.fill();
      }

      requestAnimationFrame(render);
    }

    requestAnimationFrame(render);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init3DBackground);
  } else {
    init3DBackground();
  }
})();
