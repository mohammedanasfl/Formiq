// How a wide photograph is framed in a box that shows only part of it (a workout card's photo, an
// exercise's thumbnail). Both pictures are strips, wider than the box is, and are not cropped in the
// middle: the box keeps the subject in view.

// What a framed picture needs to know: its size in pixels (a test checks it against the file) and how far
// across it the subject is, from 0 at the left edge to 1 at the right.
export type ImageFraming = {
  width: number;
  height: number;
  focus: number;
};

// 0.57 as 57, without the float's trailing digits
const percent = (share: number) => Number((share * 100).toFixed(2));
const round = (value: number) => Number(value.toFixed(2));

// For a box whose height is not known in advance (a workout card grows with its words). An explicit size,
// since on Android an image otherwise keeps the asset's own size: the picture is as tall as the box and
// as wide as its own shape makes it (never narrower than the box); the subject's point is moved to
// `subjectAt` across the box (0 is its left edge, 1 its right) by putting that point of the picture's left
// edge there and sliding the picture back by its own width times the point. The box must clip
// (`overflow: 'hidden'`): the picture is wider than it.
//
// Measured on the Android emulator (2026-10-21): the percent height is honored but the width is NOT
// derived from `aspectRatio`; the picture is laid out at the file's own width in dp (737 for core-abs). The
// picture is therefore drawn at that width and the box's height, and `cover` fits it, which crops it
// vertically by as much as the box is shorter than the file is tall. A card is within a few percent of the
// photo files' pixel heights (138 to 223 dp, files 138 to 215 px), so nothing visible is lost; a card much
// shorter than its photo would lose the top and bottom of it. Use `framedImageStyleInBox` where the box
// has a fixed size.
export function framedImageStyle(framing: ImageFraming | null, subjectAt: number) {
  if (!framing) return { width: '100%', height: '100%' } as const;
  return {
    position: 'absolute',
    top: 0,
    height: '100%',
    minWidth: '100%',
    aspectRatio: framing.width / framing.height,
    left: `${percent(subjectAt)}%`,
    transform: [{ translateX: `${-percent(framing.focus)}%` as `${number}%` }],
  } as const;
}

// For a box of a fixed size in dp (an exercise's thumbnail). Every number is explicit, so nothing depends
// on how the platform lays an image out: the picture is as tall as the box and exactly as wide as its shape
// makes it, and its subject's point is put at `subjectAt` across the box, held back so the picture never
// leaves bare box on either side.
export function framedImageStyleInBox(
  framing: ImageFraming | null,
  box: { width: number; height: number },
  subjectAt: number,
) {
  if (!framing) return { width: box.width, height: box.height } as const;
  const width = Math.max(box.height * (framing.width / framing.height), box.width);
  const left = Math.min(0, Math.max(box.width - width, box.width * subjectAt - framing.focus * width));
  return { position: 'absolute', top: 0, left: round(left), width: round(width), height: box.height } as const;
}
