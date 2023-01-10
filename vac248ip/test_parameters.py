import sys
import time
from typing import List
from .vac248ip import Vac248IpCamera
from .vac248ip_base import Vac248IpGamma, Vac248IpShutter, Vac248IpVideoFormat


class Cameras:
    def __init__(self, addresses: List[str], video_format: Vac248IpVideoFormat = Vac248IpVideoFormat.FORMAT_960x600):
        self.__addresses = addresses
        self.__video_format = video_format
        self.__cameras = None

    def __getitem__(self, item: int) -> Vac248IpCamera:
        return self.__cameras[item]

    def __iter__(self):
        return iter(self.__cameras)

    def __len__(self) -> int:
        return len(self.__cameras)

    def __enter__(self) -> "Cameras":
        self.__cameras = [Vac248IpCamera(address=address, video_format=self.__video_format)
                          for address in self.__addresses]
        for camera in self.__cameras:
            camera.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for camera in self.__cameras:
            camera.__exit__(exc_type, exc_val, exc_tb)
        self.__cameras = None


def dump_image(camera: Vac248IpCamera, camera_number: int, attempt_number: int):
    print("shutter: {}, gamma: {}, auto_gain_expo: {}, max_gain_auto: {}, contrast_auto: {}, exposure: {}, "
          "sharpness: {}, gain_analog: {}, gain_digital: {}... ".
          format(camera.shutter, camera.gamma, camera.auto_gain_expo, camera.max_gain_auto, camera.contrast_auto,
                 camera.exposure, camera.sharpness, camera.gain_analog, camera.gain_digital), end="")
    print("Getting frame #{} from camera #{}...".format(attempt_number, camera_number), end="")
    start_time = time.monotonic()
    frame, frame_number = camera.frame
    print(" => Got frame #{} (Frame get time: {}).".format(frame_number, time.monotonic() - start_time))
    with open("bitmap_{}_{}_{}.bmp".format(camera_number, attempt_number, frame_number), "wb") as file:
        file.write(camera.get_encoded_bitmap(update=False)[0])


def main(argv: List[str]) -> int:
    """
    Usage: ...command... FRAMES_COUNT CAMERA1[:PORT1] [CAMERA2[:PORT2] ...]
    """

    with Cameras(addresses=argv[2:], video_format=Vac248IpVideoFormat.FORMAT_1920x1200) as cameras:
        frames = int(argv[1])
        series_done = 0

        def dump_frames():
            nonlocal series_done

            for attempt_number in range(frames):
                for camera_number, camera in enumerate(cameras):
                    dump_image(camera, camera_number, attempt_number + frames * series_done)

            series_done += 1

        parameters = {
            "shutter": (Vac248IpShutter.SHUTTER_GLOBAL, Vac248IpShutter.SHUTTER_ROLLING),
            "gamma": (Vac248IpGamma.GAMMA_1, Vac248IpGamma.GAMMA_07, Vac248IpGamma.GAMMA_045),
            "auto_gain_expo": (True, False),
            "max_gain_expo": range(1, 11),
            "contrast_auto": range(-10, 71),
            "exposure": range(0x01, 0xbe + 1),
            "sharpness": range(0, 9),
            "gain_analog": range(1, 5),
            "gain_digital": range(1, 49)
        }
        for parameter, values in parameters.items():
            print("\nParameter: {} = {}".format(parameter, values))
            for value in values:
                for camera in cameras:
                    setattr(camera, parameter, value)
                dump_frames()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
