(All code in this repository has been reviewed or rewritten by humans, this README has been written by a human)

# Lup

A meta repository for building self-improving ClaudeAgentSDK

# Why this repo?

# Overview

## Claude code plugin

This repository contains many quality of life improvements over the barebone claude code experience:

- Hooks for automatically aproving and denying edition and code executions: I am too worried with potential prompt injections and hallucination to let Claude Code run python unprompted. Likewise, I have found that letting claude code in auto-edit mode makes a patch of code that's quite unreadable with many questionable decision, no matter the initial direction and content of Claude.md. On the other hand, manually reviewing everything is exhausting and leads to counterproductive decision-fatigue where you just approve everything repeatedly. I have found that auto-denying python calls while pre-approving investigative commands (see #devtools) means it's manageable, and same for auto-accepting small edits.
- Commands and meta-commands

## Claude commands

## Devtools

### Agent

### Human

# Getting started
