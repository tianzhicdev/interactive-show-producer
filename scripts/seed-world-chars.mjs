import { neon } from "@neondatabase/serverless";
import fs from "fs";
import path from "path";

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) { console.error("DATABASE_URL required"); process.exit(1); }

const sql = neon(DATABASE_URL);
const dataDir = path.resolve(process.env.HOME, "Downloads/interactive_show_v2_20260530");
const structure = JSON.parse(fs.readFileSync(path.join(dataDir, "structure.json"), "utf8"));
const pid = "85d54c23-3eca-410f-b346-d374bbb814c6";

// Build world settings from structure
const worldData = {
  player_stats: structure.player_stats,
  fork_points: structure.fork_points,
  endings: structure.endings,
  delayed_consequences: structure.delayed_consequences,
  conditional_outcomes: structure.conditional_outcomes,
  threshold_triggers: structure.threshold_triggers,
  hidden_elements: structure.hidden_elements,
  stats: structure.stats,
  dead_ends: structure.dead_ends,
};

// Extract characters from episode scenes
const charMap = new Map();
for (const ep of structure.episodes) {
  for (const scene of (ep.scenes || [])) {
    for (const char of (scene.characters || [])) {
      if (!charMap.has(char)) charMap.set(char, new Set());
      charMap.get(char).add(ep.id);
    }
  }
}

async function seed() {
  await sql`INSERT INTO world_settings (project_id, version, setting_data)
            VALUES (${pid}, 1, ${JSON.stringify(worldData)})`;
  console.log("world_settings inserted");

  let i = 0;
  for (const [name, epSet] of charMap) {
    const profile = { appearances: [...epSet].sort() };
    await sql`INSERT INTO characters (project_id, version, name, profile_data)
              VALUES (${pid}, 1, ${name}, ${JSON.stringify(profile)})`;
    i++;
  }
  console.log(`characters inserted: ${i}`);
}

seed().catch(e => console.error(e));
