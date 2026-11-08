# Sharing drafts

## Bluesky

Built a read-only disk analyser for Coding Challenge #145. It distinguishes allocated from apparent size, avoids following symlinks, counts hard-linked storage once, and ranks the biggest files. Python, no runtime dependencies.

Project: [add GitHub repository link]

#Python #CodingChallenges

## Substack Note

I built a first version of a disk analyser for John Crickett’s Coding Challenge #145.

It scans a directory without changing anything, reports allocated and apparent size separately, avoids following symlinks, and avoids counting hard-linked storage twice. It also shows progress, ranks the largest files, and gives a compact treemap overview in the terminal.

The exercise highlights how filesystem size can be misleading: sparse files, hard links, and directory totals all need different handling. This version is intentionally read-only; interactive cleanup and a full graphical treemap are still future steps.

Code: [add GitHub repository link]
Challenge: https://codingchallenges.substack.com/p/coding-challenge-145-disk-analyser

#Python #CodingChallenges #BuildInPublic
