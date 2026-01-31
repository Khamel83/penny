#!/usr/bin/env node

/**
 * Penny Telegram Bot
 *
 * Penny is a voice assistant layer built on top of OpenClaw.
 * This bot handles Telegram-based voice-to-action routing.
 *
 * Uses @PennyMoltBot
 */

const TelegramBot = require('node-telegram-bot-api');
const fs = require('fs');
const path = require('path');

// Load token from secrets.json
const secretsPath = path.join(__dirname, 'data', 'secrets.json');
const TELEGRAM_TOKEN = JSON.parse(fs.readFileSync(secretsPath, 'utf8')).telegram_bot_token;
const PENNY_API = process.env.PENNY_API_URL || 'http://localhost:8888';
const PENNY_INGEST = `${PENNY_API}/api/ingest`;

// Create bot with polling
const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });

console.log('🎙️ Penny Telegram Bot (@PennyMoltBot) starting...');
console.log(`Forwarding messages to Penny at ${PENNY_INGEST}`);

// Helper function to call Penny API
async function callPenny(text, user) {
  const response = await fetch(PENNY_INGEST, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: text,
      source: 'telegram',
      user_id: String(user.id),
      username: user.username,
      chat_id: String(user.id)
    })
  });
  
  const responseText = await response.text();
  
  if (!response.ok) {
    throw new Error(`Penny API error: ${response.status} - ${responseText}`);
  }
  
  // Try to parse as JSON
  try {
    return JSON.parse(responseText);
  } catch (e) {
    throw new Error(`Invalid JSON from Penny: ${responseText.substring(0, 200)}`);
  }
}

// Handle all text messages (skip commands)
bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text;

  // Skip commands starting with / (except /help and /start)
  if (text && text.startsWith('/') && text !== '/help' && text !== '/start') {
    return;
  }

  // Handle /help and /start
  if (text === '/help' || text === '/start') {
    const help = `🎙️ *Penny - Voice-to-Action Routing*

I classify and route your messages to services:

• *Shopping* → Google Keep
• *Media* → Jellyseerr  
• *Reminder/Calendar/Notes* → Apple apps
• *Smart Home* → Home Assistant
• *Work* → TrojanHorse

*Just send me a message!*

Examples:
• Add milk and eggs to my shopping list
• Can you download The Matrix
• Remind me to call dentist tomorrow
• Turn off all the lights`;
    
    await bot.sendMessage(chatId, help, { parse_mode: 'Markdown' });
    return;
  }

  // Skip empty messages
  if (!text) {
    return;
  }

  const username = msg.from.username || msg.from.first_name || 'User';
  console.log(`[${new Date().toISOString()}] @${username}: "${text}"`);

  try {
    const result = await callPenny(text, msg.from);

    if (result.error) {
      await bot.sendMessage(chatId, `❌ Error: ${result.error}`);
      return;
    }

    const { item } = result;
    const classification = item.classification;
    const confidence = Math.round(item.confidence * 100);
    const routed = item.routed_to ? `→ ${item.routed_to}` : '(stored in memory)';

    // Build friendly response
    let reply = `✅ *${classification.toUpperCase()}* ${routed}\n\n`;
    reply += `📊 Confidence: ${confidence}%`;

    // Add routing-specific details
    if (item.routing_data) {
      const data = item.routing_data;
      if (data.items) reply += `\n\n🛒 Items: ${data.items.join(', ')}`;
      if (data.title) reply += `\n\n🎬 ${data.title}${data.type ? ` (${data.type})` : ''}`;
      if (data.task) reply += `\n\n📋 Task: ${data.task}`;
      if (data.summary) reply += `\n\n📝 ${data.summary}`;
    }

    await bot.sendMessage(chatId, reply, { parse_mode: 'Markdown' });
    console.log(`[${new Date().toISOString()}] → ${classification} (${confidence}%) → ${item.routed_to || 'memory'}`);

  } catch (error) {
    console.error(`[${new Date().toISOString()}] Error:`, error.message);
    await bot.sendMessage(chatId, `❌ Failed: ${error.message}`);
  }
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('Shutting down...');
  bot.stopPolling();
  process.exit(0);
});

console.log('✅ Penny bot is listening for messages...');
console.log('Send /help for usage information');
