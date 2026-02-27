(All code in this repository has been reviewed or rewritten by humans, this README has been written by a human)

# Lup

A meta repository for speed-boosting your claude code development, especially to create self-improving [ClaudeAgentSDK] applications

[[image1]]
[[image2]]

# Why this repo?

I believe that claude code may be underappreciated right now. Not just the agent, but its [SDK]. The SDK of claude code allows it to:

- Think through a task by using many tools to fetch information, and decompose it carefully
- Delegate part of its task to other agents through tool calls that augment or gatekeep the results
- React in real time through auto-deny hooks and get_current_state tools

... all of that through your claude code subscription, without having to pay any extra API cost or setup.

The basic pattern is to create a ClaudeAgentSDK client, connect many tools to it, and let claude code decide when to call them, and prompt it about the general shape of it. And to ask claude code to write it, create commands to modify itself, to modify its own Claude.md to document the ClaudeAgentSDK patterns in use, ...

Over writing and reusing this technique many time, I have come to find that having a template and plugin as a base can really speed up the development and the coherence of Claude. This repository is a sort of extract of all the common patterns and plugin command and scripts I have found useful.

It is a template to help bootstrap this pattern and create your own ClaudeAgentSDK easily

# Examples

Some examples of things I'm using this self-scaffolding for (still in early WIP):

- [joy.void.joy-bot]: Not yet opensource. A forecasting agent written for the [FutureEval] tournament.
- [mettle]: A bot whose main tool is writing its own tools
- [botc]: Having bots compete with one another while playing [Blood on the Clocktower]
- [harmon]: real-time discord bot focused on presence and reactivity/helpfulness (still early WIP)

But you could use it for so much more. Real-time monitoring, mathematical proofs or formal verification ([[AIMO3]]), anything that can be automated where the kind of resources or tools it needs is easy to explore and refine

# Getting started

To start using this repo either:

- For a fresh repository: Use the "Use this template" button on github, or clone this repository. In the newly cloned repository, use /lup:init [description of your project] or /lup:brainstorm to first flesh out the broad shape of it
- For

## Intended workflow

The intended workflow while using this repository is to:

- Have it cloned in a bare repo
- Creating a worktree to tree/main: ``git clone
- When working on a new feature, branching off from it with `lup-devtools dev worktree <branch-name>`
- Going into this new branch, and working on it there
- Then /lup:commit it
- When it works and you've tested it works well /lup:rebase it
- Review it in github before merging it
- Call /lup:close on the merged branch or /lup:clean-gone on any branch (like main) to keep the worktree clean

## General patterns

[fill from Claude.md?]

# Overview

This repository contains many elements and code template that are designed to make creating your own scaffolding with ClaudeAgentSDK seamless:

- Code template and utilities to create a ClaudeAgentSDK with appropriate tools and hooks from scratch
- Many quality of life improvement to the claude code experience through a lup plugin
- devtools aimed at both human use and agent use
- Feedback loop and note-taking mechanisms for auditing and improving your agent

## Code template

## Claude code plugin

This repository contains many quality of life improvements over the barebone claude code experience:

- Hooks for automatically aproving and denying edition and code executions: I am too worried with potential prompt injections and hallucination to let Claude Code run python unprompted. Likewise, I have found that letting claude code in auto-edit mode makes a patch of code that's quite unreadable with many questionable decision, no matter the initial direction and content of Claude.md. On the other hand, manually reviewing everything is exhausting and leads to counterproductive decision-fatigue where you just approve everything repeatedly. I have found that auto-denying python calls while pre-approving investigative commands (see #devtools) means it's manageable, and same for auto-accepting small edits.
- Commands and meta-commands for modifying your experience whenever you find a pain point (like /lup:add-command or /lup:meta)
- subagents specialized in reading the traces and the different versions of your project, and understanding the strength of one version over another
- fzf fuzzy matching for @ file references

## Claude commands

To speed up development, many claude commands and meta-commands are built in this repository:

- add-command
- modify-command

- brainstorm

- bump

- commit
- rebase
- merge-conflict
- clean-gone
- close

- create-investigator
- debug

- feedback-loop

- hooks

- refactor
- refactor-tools

- update
- import

## Devtools

### Agent

### Human
