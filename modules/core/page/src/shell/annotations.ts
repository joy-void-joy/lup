// What the shell marks its own transactions with, apart from the operator's, and what tells what's drawn beside the
// text to draw again: kept apart from the shell, so what it uses (its comments, its margin) reads them without
// importing the shell itself.

import { Annotation, StateEffect } from "@codemirror/state";

/** Marks a transaction the shell makes, as views answer or as it lays a comment out, rather than one the operator's keys make. */
export const fromCore = Annotation.define<boolean>();

/**
 * Marks a transaction after which what the shell draws beside the text may have changed, though the text didn't: what's
 * open (a fold read as it opens, or holding nothing, has no range to fold), what's chosen, or what a comment says of
 * itself.
 */
export const redrawn = StateEffect.define<null>();
