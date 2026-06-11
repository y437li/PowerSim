#!/usr/bin/env node
/**
 * scripts/generate_gansu_glbs.js
 *
 * Generates the 4 Gansu parity GLB v2 files referenced by assets/3d/registry.json v1.0.1.
 * Each file contains box-primitive geometry sized to the registered dims_m, with named
 * nodes/materials matching the animation hooks.
 *
 * Outputs:
 *   assets/3d/turbines/vestas-v150-4.2.glb    node "Rotor" + "Tower"
 *   assets/3d/pv/trina-vertex-n-670w.glb      material "PVSurface"
 *   assets/3d/batteries/catl-lmp-300mwh.glb   node "SOCFillMesh" + "Container"
 *   assets/3d/grid/pcc-substation-945mw.glb   (no animation hook)
 *
 * Usage: node scripts/generate_gansu_glbs.js
 *
 * Contract: contracts/assets/gansu_glb_models.md §3, §4, §5
 */

import { writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const ASSETS_3D = join(__dirname, "../assets/3d");

// ---------------------------------------------------------------------------
// Box geometry helpers (contract §5)
// ---------------------------------------------------------------------------

/**
 * Build 8 Float32 vertices for an axis-aligned box.
 * Base-centre convention: pivot at {0,0,0} = base centre
 *   xMin..xMax centred around 0, yMin = 0 (base), zMin..zMax centred around 0.
 */
function boxVerts(xMin, yMin, zMin, xMax, yMax, zMax) {
  // 8 corners
  return new Float32Array([
    xMin, yMin, zMin, // 0 back-bottom-left
    xMax, yMin, zMin, // 1 back-bottom-right
    xMax, yMax, zMin, // 2 back-top-right
    xMin, yMax, zMin, // 3 back-top-left
    xMin, yMin, zMax, // 4 front-bottom-left
    xMax, yMin, zMax, // 5 front-bottom-right
    xMax, yMax, zMax, // 6 front-top-right
    xMin, yMax, zMax, // 7 front-top-left
  ]);
}

/** 36 Uint16 indices for a box (CCW winding viewed from outside). */
const BOX_INDICES = new Uint16Array([
  4, 5, 6,  4, 6, 7,  // front  (z = zMax)
  0, 3, 2,  0, 2, 1,  // back   (z = zMin)
  0, 4, 7,  0, 7, 3,  // left   (x = xMin)
  5, 1, 2,  5, 2, 6,  // right  (x = xMax)
  3, 7, 6,  3, 6, 2,  // top    (y = yMax)
  4, 0, 1,  4, 1, 5,  // bottom (y = yMin)
]);

/** Pad a Buffer to a 4-byte boundary (GLB alignment requirement). */
function padTo4(buf, fillByte) {
  const rem = buf.length % 4;
  if (rem === 0) return buf;
  return Buffer.concat([buf, Buffer.alloc(4 - rem, fillByte ?? 0)]);
}

// ---------------------------------------------------------------------------
// GLB assembly (contract §5)
// ---------------------------------------------------------------------------

/**
 * Pack one or more box meshes into a single BIN buffer.
 * Returns {binBuf, meshLayouts} where meshLayouts[i] = {vertByteOffset, idxByteOffset}.
 * All offsets are within binBuf.
 */
function packBoxMeshes(boxList) {
  const chunks = [];
  const layouts = [];
  let offset = 0;
  for (const verts of boxList) {
    const vertBuf = Buffer.from(verts.buffer, verts.byteOffset, verts.byteLength);
    const idxBuf = Buffer.from(
      BOX_INDICES.buffer,
      BOX_INDICES.byteOffset,
      BOX_INDICES.byteLength,
    );
    layouts.push({ vertByteOffset: offset, idxByteOffset: offset + 96 });
    offset += 96 + 72; // 8 × 12 bytes verts + 36 × 2 bytes indices
    chunks.push(vertBuf, idxBuf);
  }
  return { binBuf: Buffer.concat(chunks), layouts };
}

/**
 * Assemble a GLB v2 binary from a glTF JSON object and a BIN buffer.
 * The JSON is space-padded and the BIN is zero-padded to 4-byte boundaries.
 */
function buildGLB(gltfJson, binBuf) {
  // JSON chunk: UTF-8 string padded with spaces to 4-byte boundary
  let jsonStr = JSON.stringify(gltfJson);
  while (jsonStr.length % 4 !== 0) jsonStr += " ";
  const jsonBuf = Buffer.from(jsonStr, "utf8");

  // BIN chunk: zero-padded to 4-byte boundary
  const binPadded = padTo4(binBuf, 0);

  const totalLength =
    12 + // header
    8 + jsonBuf.length + // JSON chunk header + data
    8 + binPadded.length; // BIN chunk header + data

  const out = Buffer.alloc(totalLength);
  let pos = 0;

  // Header
  out.write("glTF", pos, "ascii"); pos += 4;
  out.writeUInt32LE(2, pos); pos += 4;     // version
  out.writeUInt32LE(totalLength, pos); pos += 4; // totalLength

  // JSON chunk
  out.writeUInt32LE(jsonBuf.length, pos); pos += 4;
  out.writeUInt32LE(0x4e4f534a, pos); pos += 4; // "JSON"
  jsonBuf.copy(out, pos); pos += jsonBuf.length;

  // BIN chunk
  out.writeUInt32LE(binPadded.length, pos); pos += 4;
  out.writeUInt32LE(0x004e4942, pos); pos += 4; // "BIN\0"
  binPadded.copy(out, pos);

  return out;
}

/**
 * Build an accessor descriptor. POSITION accessors require min/max.
 */
function posAccessor(bufferView, verts) {
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (let i = 0; i < verts.length; i += 3) {
    if (verts[i]     < minX) minX = verts[i];
    if (verts[i + 1] < minY) minY = verts[i + 1];
    if (verts[i + 2] < minZ) minZ = verts[i + 2];
    if (verts[i]     > maxX) maxX = verts[i];
    if (verts[i + 1] > maxY) maxY = verts[i + 1];
    if (verts[i + 2] > maxZ) maxZ = verts[i + 2];
  }
  return {
    bufferView,
    componentType: 5126, // FLOAT
    count: 8,
    type: "VEC3",
    min: [minX, minY, minZ],
    max: [maxX, maxY, maxZ],
  };
}

function idxAccessor(bufferView) {
  return {
    bufferView,
    componentType: 5123, // UNSIGNED_SHORT
    count: 36,
    type: "SCALAR",
  };
}

// ---------------------------------------------------------------------------
// 1. Wind turbine: vestas-v150-4.2 (150×166×150 m)
//    Nodes: Tower (mesh=0), Rotor (mesh=1)
// ---------------------------------------------------------------------------

function buildTurbine() {
  // Tower: narrow tall box, full height 166 m, 16 m footprint
  const towerV = boxVerts(-8, 0, -8, 8, 166, 8);
  // Rotor: flat wide box representing rotor disc + blades (150 m span, 6 m thick)
  // Centred at hub height (y ≈ 161), spanning full 150 m (x) and 6 m (z)
  const rotorV = boxVerts(-75, 158, -3, 75, 164, 3);

  const { binBuf, layouts } = packBoxMeshes([towerV, rotorV]);

  // bufferViews: [0]=towerVerts, [1]=towerIdx, [2]=rotorVerts, [3]=rotorIdx
  const bufferViews = [
    { buffer: 0, byteOffset: layouts[0].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[0].idxByteOffset,  byteLength: 72 },
    { buffer: 0, byteOffset: layouts[1].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[1].idxByteOffset,  byteLength: 72 },
  ];

  const gltf = {
    asset: { version: "2.0", generator: "generate_gansu_glbs.js" },
    scene: 0,
    scenes: [{ name: "Scene", nodes: [0, 1] }],
    nodes: [
      { name: "Tower", mesh: 0 },
      { name: "Rotor", mesh: 1 },
    ],
    meshes: [
      { name: "TowerMesh",
        primitives: [{ attributes: { POSITION: 0 }, indices: 1 }] },
      { name: "RotorMesh",
        primitives: [{ attributes: { POSITION: 2 }, indices: 3 }] },
    ],
    accessors: [
      posAccessor(0, towerV),
      idxAccessor(1),
      posAccessor(2, rotorV),
      idxAccessor(3),
    ],
    bufferViews,
    buffers: [{ byteLength: binBuf.length }],
  };

  return buildGLB(gltf, binBuf);
}

// ---------------------------------------------------------------------------
// 2. PV array: trina-vertex-n-670w (40×3×20 m)
//    Material "PVSurface" (dark blue) assigned to the single primitive
// ---------------------------------------------------------------------------

function buildPV() {
  // Flat panel array: full dims 40×3×20
  const pvV = boxVerts(-20, 0, -10, 20, 3, 10);

  const { binBuf, layouts } = packBoxMeshes([pvV]);

  const bufferViews = [
    { buffer: 0, byteOffset: layouts[0].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[0].idxByteOffset,  byteLength: 72 },
  ];

  const gltf = {
    asset: { version: "2.0", generator: "generate_gansu_glbs.js" },
    scene: 0,
    scenes: [{ name: "Scene", nodes: [0] }],
    nodes: [{ name: "PVArray", mesh: 0 }],
    meshes: [
      { name: "PVMesh",
        // material: 0 → PVSurface (reviewer check: material must be used by ≥1 primitive)
        primitives: [{ attributes: { POSITION: 0 }, indices: 1, material: 0 }] },
    ],
    materials: [
      {
        name: "PVSurface",
        pbrMetallicRoughness: {
          baseColorFactor: [0.02, 0.05, 0.25, 1.0], // dark blue
          metallicFactor: 0.3,
          roughnessFactor: 0.8,
        },
        // emissiveFactor is driven at runtime via emissiveIntensity — not baked here
        emissiveFactor: [0.0, 0.0, 0.0],
      },
    ],
    accessors: [posAccessor(0, pvV), idxAccessor(1)],
    bufferViews,
    buffers: [{ byteLength: binBuf.length }],
  };

  return buildGLB(gltf, binBuf);
}

// ---------------------------------------------------------------------------
// 3. Battery: catl-lmp-300mwh (20×5×60 m)
//    Nodes: Container (mesh=0), SOCFillMesh (mesh=1)
// ---------------------------------------------------------------------------

function buildBattery() {
  // Outer container box: full dims
  const containerV = boxVerts(-10, 0, -30, 10, 5, 30);
  // SOCFillMesh: slightly smaller inner box — scene drives scale.y ∈ [0,1] for SOC
  // Slightly inset on all sides so it's visually distinct from the outer container
  const fillV = boxVerts(-9, 0.1, -29, 9, 4.9, 29);

  const { binBuf, layouts } = packBoxMeshes([containerV, fillV]);

  const bufferViews = [
    { buffer: 0, byteOffset: layouts[0].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[0].idxByteOffset,  byteLength: 72 },
    { buffer: 0, byteOffset: layouts[1].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[1].idxByteOffset,  byteLength: 72 },
  ];

  const gltf = {
    asset: { version: "2.0", generator: "generate_gansu_glbs.js" },
    scene: 0,
    scenes: [{ name: "Scene", nodes: [0, 1] }],
    nodes: [
      { name: "Container",  mesh: 0 },
      { name: "SOCFillMesh", mesh: 1 },
    ],
    meshes: [
      { name: "ContainerMesh",
        primitives: [{ attributes: { POSITION: 0 }, indices: 1 }] },
      { name: "FillMesh",
        primitives: [{ attributes: { POSITION: 2 }, indices: 3 }] },
    ],
    accessors: [
      posAccessor(0, containerV),
      idxAccessor(1),
      posAccessor(2, fillV),
      idxAccessor(3),
    ],
    bufferViews,
    buffers: [{ byteLength: binBuf.length }],
  };

  return buildGLB(gltf, binBuf);
}

// ---------------------------------------------------------------------------
// 4. PCC substation: pcc-substation-945mw (50×15×30 m)
//    Single box, no animation hook
// ---------------------------------------------------------------------------

function buildSubstation() {
  const subV = boxVerts(-25, 0, -15, 25, 15, 15);

  const { binBuf, layouts } = packBoxMeshes([subV]);

  const bufferViews = [
    { buffer: 0, byteOffset: layouts[0].vertByteOffset, byteLength: 96 },
    { buffer: 0, byteOffset: layouts[0].idxByteOffset,  byteLength: 72 },
  ];

  const gltf = {
    asset: { version: "2.0", generator: "generate_gansu_glbs.js" },
    scene: 0,
    scenes: [{ name: "Scene", nodes: [0] }],
    nodes: [{ name: "Substation", mesh: 0 }],
    meshes: [
      { name: "SubstationMesh",
        primitives: [{ attributes: { POSITION: 0 }, indices: 1 }] },
    ],
    materials: [
      {
        name: "SubstationMaterial",
        pbrMetallicRoughness: {
          baseColorFactor: [0.35, 0.35, 0.35, 1.0], // grey
          metallicFactor: 0.1,
          roughnessFactor: 0.9,
        },
      },
    ],
    accessors: [posAccessor(0, subV), idxAccessor(1)],
    bufferViews,
    buffers: [{ byteLength: binBuf.length }],
  };

  return buildGLB(gltf, binBuf);
}

// ---------------------------------------------------------------------------
// Main: generate all 4 files
// ---------------------------------------------------------------------------

const OUTPUTS = [
  { file: "turbines/vestas-v150-4.2.glb",   build: buildTurbine,    desc: "wind turbine (Tower + Rotor)" },
  { file: "pv/trina-vertex-n-670w.glb",       build: buildPV,         desc: "PV array (PVSurface material)" },
  { file: "batteries/catl-lmp-300mwh.glb",   build: buildBattery,    desc: "battery (Container + SOCFillMesh)" },
  { file: "grid/pcc-substation-945mw.glb",   build: buildSubstation, desc: "PCC substation" },
];

let ok = true;
for (const { file, build, desc } of OUTPUTS) {
  const outPath = join(ASSETS_3D, file);
  try {
    const buf = build();
    writeFileSync(outPath, buf);
    console.log(`wrote ${file} (${buf.length} bytes) — ${desc}`);
  } catch (err) {
    console.error(`FAILED ${file}: ${err.message}`);
    ok = false;
  }
}

if (!ok) {
  process.exit(1);
}
console.log("All 4 Gansu GLBs generated successfully.");
