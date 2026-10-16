#!/usr/bin/env node
// Checks data/*.json against docs/DATA.md. No dependencies. Exit 1 on any error.
import { readFileSync } from "node:fs";

const errors = [];
const err = (f, m) => errors.push(`${f}: ${m}`);
const isISO = (s) => typeof s === "string" && !Number.isNaN(Date.parse(s));
const num = (v) => typeof v === "number" && Number.isFinite(v);
const SECRETISH = /(AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|sk-[A-Za-z0-9_-]{20,}|auth_token|ct0=)/;

function load(name) {
  const f = `data/${name}.json`;
  let raw;
  try { raw = readFileSync(f, "utf8"); } catch { err(f, "missing"); return null; }
  if (SECRETISH.test(raw)) err(f, "looks like it contains a key or cookie");
  let d;
  try { d = JSON.parse(raw); } catch (e) { err(f, `invalid JSON: ${e.message}`); return null; }
  if (d.schema_version !== 1) err(f, "schema_version must be 1");
  if (!isISO(d.generated_at)) err(f, "generated_at must be ISO 8601");
  return d;
}
const arr = (f, v, key, max) => {
  if (!Array.isArray(v)) { err(f, `${key} must be an array`); return []; }
  if (max && v.length > max) err(f, `${key} has ${v.length} items, max ${max}`);
  return v;
};
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const x = load("x_trends");
const ids = new Set();
if (x) arr("x_trends", x.stories, "stories", 15).forEach((s, i) => {
  if (!SLUG.test(s.id || "")) err("x_trends", `stories[${i}].id must be a kebab-case slug`);
  if (ids.has(s.id)) err("x_trends", `duplicate id ${s.id}`);
  ids.add(s.id);
  if (!s.title) err("x_trends", `stories[${i}].title required`);
  if (!num(s.heat) || s.heat < 0 || s.heat > 100) err("x_trends", `stories[${i}].heat must be 0-100`);
  if (s.top_posts) arr("x_trends", s.top_posts, `stories[${i}].top_posts`, 3);
});

const y = load("youtube_coverage");
if (y) arr("youtube_coverage", y.stories, "stories", 15).forEach((s, i) => {
  if (!s.story_id) err("youtube_coverage", `stories[${i}].story_id required`);
  if (!num(s.video_count)) err("youtube_coverage", `stories[${i}].video_count must be a number`);
  if (s.coverage && !["none", "low", "medium", "high"].includes(s.coverage)) err("youtube_coverage", `stories[${i}].coverage invalid`);
  if (s.gap_score != null && (!num(s.gap_score) || s.gap_score < 0 || s.gap_score > 100)) err("youtube_coverage", `stories[${i}].gap_score must be 0-100`);
  if (s.top_videos) arr("youtube_coverage", s.top_videos, `stories[${i}].top_videos`, 10);
});

const c = load("content_packs");
if (c) arr("content_packs", c.packs, "packs", 5).forEach((p, i) => {
  const f = "content_packs", at = `packs[${i}]`;
  if (!p.story_id) err(f, `${at}.story_id required`);
  if (!p.video?.title || !p.video?.thumbnail_text || !p.video?.hook) err(f, `${at}.video needs title, thumbnail_text, hook`);
  if (!Array.isArray(p.short?.beats) || !p.short.beats.length) err(f, `${at}.short.beats required`);
  const n = p.carousel?.slides?.length || 0;
  if (n < 5 || n > 8) err(f, `${at}.carousel.slides must have 5-8 slides (has ${n})`);
  if (typeof p.x_post !== "string" || p.x_post.length > 280) err(f, `${at}.x_post must be a string of 280 chars max`);
});

const n = load("claude_code_news");
if (n) arr("claude_code_news", n.items, "items", 8).forEach((it, i) => {
  if (!it.version || !it.title) err("claude_code_news", `items[${i}] needs version and title`);
});

const ch = load("channel_stats");
if (ch) {
  if (!ch.channel?.title) err("channel_stats", "channel.title required");
  arr("channel_stats", ch.recent_videos, "recent_videos", 8).forEach((v, i) => {
    if (!v.title || !num(v.views)) err("channel_stats", `recent_videos[${i}] needs title and views`);
  });
}

const l = load("refresh_log");
if (l) arr("refresh_log", l.entries, "entries", 60).forEach((e, i) => {
  if (!isISO(e.at)) err("refresh_log", `entries[${i}].at must be ISO 8601`);
  if (!["x_scan", "cloud_refresh"].includes(e.job)) err("refresh_log", `entries[${i}].job must be x_scan or cloud_refresh`);
  if (!["ok", "partial", "error"].includes(e.status)) err("refresh_log", `entries[${i}].status must be ok, partial or error`);
});

if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("data/ OK");
