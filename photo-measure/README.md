# Photo measure

Read real millimetres and the camera angle from a phone photo of a printed
ArUco card. Print the PM-2 card (240 mm C shape, ArUco `DICT_4X4_50` ids
20-26, mm rulers), put the object inside the C, take a photo, run:

```
pip install opencv-python numpy
python photo_measure.py PHOTO.jpg --focal-auto
python photo_measure.py PHOTO.jpg --measure x1,y1,x2,y2   # image px -> mm on the card plane
```

It writes `PHOTO_rectified.png` (top-down view of the card plane, 10 px per
mm, 10 mm grid) and `PHOTO_measure.json`, and prints the scale, tilt and
distance. Distances are valid on the card plane only: the top of a tall
object looks bigger because it is closer to the camera.

- `pm2_marker_spec.json`: every marker corner in card mm (origin outer
  bottom-left corner, x right, y up). The script loads it from this folder.
- One visible marker is enough for the scale; 2 or more are better. Markers
  covered by the object are skipped.
- Printed cards can shrink a little (PLA about 0.3 %): `--board-scale 0.997`
  or `--marker-positions measured.json` with calipered corners.
- The script also reads the older PM-1 card (100 mm, ids 0-3) and a 30 mm
  cube (ids 10-15).

Tested on one real phone photo of the printed card (1512 x 2016 px, 18 deg
tilt): all 7 markers found, homography rms 1.3 px.

Card files (STL, STEP, 3MF): see the model listing, linked from the
repository README.
