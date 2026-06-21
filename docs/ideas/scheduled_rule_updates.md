# Scheduled Rule Updates Design

This document details the automated update mechanism designed to keep rule repositories synchronized and indexed at 2:00 AM every 14 days using the OS scheduler (Windows Task Scheduler / Linux Cron).

## Problem Statement
How Might We automatically sync and index rules every 2 weeks at 2:00 AM without interrupting users or daytime compute, and resolve service dependencies (Docker / Ollama) on the fly?

## Recommended Direction
A daily checker task running at 2:00 AM. It inspects a `.last_sync` timestamp file.
- If last sync < 14 days, exits immediately.
- If last sync >= 14 days, initiates full synchronization:
  1. Bootstraps Docker & Ollama.
  2. Pulls remote git repositories via sparse-checkout.
  3. Generates vector embeddings for rules via Ollama.
  4. Saves new timestamp to `.last_sync`.

## Implementation Files
- **Windows**: `cron_sync.ps1`
- **Linux/macOS**: `cron_sync.sh`
- **Gitignore**: Ignored `.last_sync` timestamp to prevent cache collision.

## Key Assumptions to Validate
- The Task Scheduler can wake the PC from sleep if sleep options allow it.
- Docker can start in daemon mode without active GUI session login.
- Internet connectivity is active at 2:00 AM.
