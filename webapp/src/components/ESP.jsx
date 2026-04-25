import { useEffect, useRef } from "react";

// Approximate CS2 player height in game units (feet → top of head)
const PLAYER_H = 72;

// Corner-box stroke length as a fraction of box dimension
const CORNER_FRAC = 0.22;

/**
 * Project a CS2 world position to canvas pixel coordinates.
 * matrix: 16-element row-major VMatrix from dwViewMatrix
 */
function w2s(wx, wy, wz, matrix, sw, sh) {
  const cx = matrix[0] * wx + matrix[1] * wy + matrix[2]  * wz + matrix[3];
  const cy = matrix[4] * wx + matrix[5] * wy + matrix[6]  * wz + matrix[7];
  const cw = matrix[12]* wx + matrix[13]* wy + matrix[14] * wz + matrix[15];
  if (cw < 0.001) return null; // behind camera
  return {
    x: (sw / 2) * (1 + cx / cw),
    y: (sh / 2) * (1 - cy / cw),
  };
}

function drawCornerBox(ctx, x, y, w, h, color, thickness = 1.5) {
  const cx = w * CORNER_FRAC;
  const cy = h * CORNER_FRAC;
  ctx.strokeStyle = color;
  ctx.lineWidth = thickness;
  ctx.beginPath();
  // top-left
  ctx.moveTo(x,     y + cy); ctx.lineTo(x,     y    ); ctx.lineTo(x + cx, y    );
  // top-right
  ctx.moveTo(x+w-cx,y      ); ctx.lineTo(x + w, y    ); ctx.lineTo(x + w,  y+cy);
  // bottom-left
  ctx.moveTo(x,     y+h-cy ); ctx.lineTo(x,     y + h); ctx.lineTo(x + cx, y+h );
  // bottom-right
  ctx.moveTo(x+w-cx,y+h    ); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w,  y+h-cy);
  ctx.stroke();
}

function drawHealthBar(ctx, x, y, h, hp) {
  const frac  = Math.max(0, Math.min(1, hp / 100));
  const barW  = 3;
  const gap   = 3;
  const bx    = x - barW - gap;
  const filled = h * frac;

  // Background
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(bx, y, barW, h);

  // Fill — green → yellow → red
  const hue = frac * 120; // 120=green, 60=yellow, 0=red
  ctx.fillStyle = `hsl(${hue},100%,45%)`;
  ctx.fillRect(bx, y + h - filled, barW, filled);
}

function drawLabel(ctx, text, cx, y, color = "#fff", shadowColor = "rgba(0,0,0,0.8)") {
  ctx.font = "bold 11px 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  // Shadow
  ctx.fillStyle = shadowColor;
  ctx.fillText(text, cx + 1, y + 1);
  ctx.fillStyle = color;
  ctx.fillText(text, cx, y);
}

export default function ESP({ playerArray = [], localTeam, viewMatrix = [] }) {
  const canvasRef = useRef(null);

  // Keep canvas sized to the full overlay window
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resize = () => {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // Redraw every time data arrives (10 Hz)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const sw  = canvas.width;
    const sh  = canvas.height;

    ctx.clearRect(0, 0, sw, sh);

    if (!viewMatrix || viewMatrix.length < 16) return;

    for (const p of playerArray) {
      if (p.m_is_dead) continue;

      const { x: wx, y: wy, z: wz = 0 } = p.m_position;

      const feet = w2s(wx, wy, wz,            viewMatrix, sw, sh);
      const head = w2s(wx, wy, wz + PLAYER_H, viewMatrix, sw, sh);

      if (!feet || !head) continue;

      // Cull if both points are outside the screen
      const margin = 200;
      if (feet.x < -margin || feet.x > sw + margin) continue;
      if (feet.y < -margin || feet.y > sh + margin) continue;

      const boxH = Math.abs(feet.y - head.y);
      if (boxH < 4) continue; // too small / too far

      const boxW  = boxH * 0.45;
      const boxX  = head.x - boxW / 2;
      const boxY  = head.y;

      const isEnemy   = p.m_team !== localTeam;
      const boxColor  = isEnemy ? "#ff3c3c" : "#3cf0ff";
      const nameColor = isEnemy ? "#ffaaaa" : "#aaf0ff";

      // Corner box
      drawCornerBox(ctx, boxX, boxY, boxW, boxH, boxColor);

      // Health bar
      drawHealthBar(ctx, boxX, boxY, boxH, p.m_health);

      // Name above box
      if (p.m_name) {
        drawLabel(ctx, p.m_name, head.x, boxY - 2, nameColor);
      }

      // Health number below name (if near)
      if (boxH > 30) {
        drawLabel(ctx, `${p.m_health}hp`, head.x, boxY + boxH + 12, boxColor);
      }
    }
  }, [playerArray, viewMatrix, localTeam]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
      }}
    />
  );
}
