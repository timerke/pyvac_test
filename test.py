from PIL import Image
import numpy as np
from vac248ip import Vac248IpCamera
import matplotlib.pyplot as plt

mean_frames = 3

_bz_cam = Vac248IpCamera("172.16.142.153:1024", defer_open=True, default_attempts=10)
_bz_cam.open_device()
_bz_cam.exposition = 1
_bz_cam.gain_analog = 4
print(_bz_cam.gain_analog)
_bz_cam.gain_digital = 4
img_arr = _bz_cam.get_smart_mean_frame(frames=mean_frames)[0]
_bz_cam.close_device()

plt.imshow(img_arr)
plt.colorbar()
plt.show()
#img_arr = np.zeros((100, 100), dtype=np.uint8)
img = Image.fromarray(img_arr)
img.save("test.bmp")