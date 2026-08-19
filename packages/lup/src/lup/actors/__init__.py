"""Addressable agents: one held session each, reachable while they work.

An agent a caller opens, drives for one turn and closes cannot be talked to,
because there is nothing to talk to between the call and the result. This
package is the other shape — an actor holds its session across turns, takes
mail mid-turn through a hook it never chooses to check, and asks questions
that settle without stalling whoever asked.

Nothing here knows what the actors are for. The resolver names its own kinds
and carries its own question type over the same mechanism; a research session
names different ones. That was the point of moving it: the layer was written
once against one vocabulary, and the vocabulary was never what made it work.
"""
