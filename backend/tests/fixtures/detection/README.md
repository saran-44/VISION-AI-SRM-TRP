# Detection fixtures

Add owner-supplied, legally approved gate frames here as `.jpg`, `.jpeg`,
`.png`, `.webp`, or `.bmp`. Use filenames that describe the case:

- sticker close, mid-distance, and far
- night and glare
- two buses in one frame
- a frame with no bus

Update `expected.json` with one entry per image. The value is the normalized
`bus_number` or `null` when no readable number is expected. Tests skip when no
images are present or when the optional vision dependencies are unavailable.
