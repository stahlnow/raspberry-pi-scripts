#!/usr/bin/env python
import logging
import argparse
import datetime
import subprocess
import tempfile

from logging.handlers import TimedRotatingFileHandler

from pathlib import Path

from rocketry import Rocketry
from rocketry.conds import after_success
from rocketry.args import Arg

from redbird.repos import MemoryRepo


class LagunaCamException(Exception):
    pass


app = Rocketry(
    config={
        "task_execution": "main",
        "silence_task_prerun": True,
        "silence_task_logging": True,
        "silence_cond_check": True,
    },
    logger_repo=MemoryRepo(),
)


def parse_args():
    def size(size):
        try:
            w, h = map(int, size.split(","))
            return w, h
        except Exception:
            raise argparse.ArgumentTypeError("Size must be w,h")

    parser = argparse.ArgumentParser(
        description="Specify recording format and upload destination"
    )
    parser.add_argument(
        "-log",
        "--log",
        default="warning",
        help="Provide logging level <debug>. Default warning",
    )
    parser.add_argument(
        "--interval",
        default="every 10 minutes",
        help="Provide interval for recording (https://github.com/Miksus/rocketry/). Default 'every 10 minutes'",
    )
    parser.add_argument(
        "-d",
        "--duration",
        default=30000,
        type=int,
        help="Duration (in ms) to record. Default 30000",
    )
    parser.add_argument(
        "-s",
        "--size",
        default=(
            1920,
            1080,
        ),
        type=size,
        help="Set video resolution <width,height>. Default 1920,1080",
    )
    args = parser.parse_args()

    levels = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
    }
    level = levels.get(args.log.lower())
    if level is None:
        sys.exit(
            f"log level given: {args.log}"
            f" -- must be one of: {' | '.join(levels.keys())}"
        )

    return (
        level,
        args.interval,
        args.duration,
        args.size,
    )


def record(width, height, duration):
    fps = 25
    bitrate = int(15e6)

    with tempfile.NamedTemporaryFile(
        delete=False, mode="w+", suffix=".h264"
    ) as output_path:
        command = [
            "raspivid",
            "-t",
            f"{duration}",
            "-w",
            f"{width}",
            "-h",
            f"{height}",
            "-fps",
            f"{fps}",
            "-b",
            f"{bitrate}",
            "-o",
            output_path.name,
        ]

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H_%M_%S")
            log.info(f"Start recording {output_path.name} at {timestamp}")
            subprocess.run(
                command,
                check=True,
                capture_output=True,
            )
            log.info(f"Successfully recorded {output_path.name}")
        except subprocess.CalledProcessError as e:
            Path(output_path.name).unlink(missing_ok=True)
            raise LagunaCamException(
                f"Unable to record video. Command was: {e.cmd}. Exit code: {e.returncode}.\nError output: {e.stderr.decode()}"
            )

        return output_path


def encode(input_path):
    with tempfile.NamedTemporaryFile(
        delete=False, mode="w+", suffix=".mp4"
    ) as output_path:

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path.name),
            "-preset",
            "ultrafast",
            "-qp",
            "0",
            str(output_path.name),
        ]

        try:
            log.info(f"Start encoding {output_path.name}")
            subprocess.run(
                command,
                check=True,
                capture_output=True,
            )
            log.info(f"Successfully encoded {output_path.name}")
        except subprocess.CalledProcessError as e:
            Path(output_path.name).unlink(missing_ok=True)
            raise LagunaCamException(
                f"Unable to encode video. Command was: {e.cmd}. Exit code: {e.returncode}.\nError output: {e.stderr.decode()}"
            )
        finally:
            Path(input_path.name).unlink(missing_ok=True)

        return output_path


def upload(input_path):
    user = "stahl"
    # server = "192.168.1.42"
    # server = "10.35.0.159"
    server = "10.35.0.182"

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H_%M_%S")
    filename = f"laboratorio_laguna_cam_{timestamp}.mp4"
    upload_relative_path = f"temp/venedig/{filename}"
    destination = f"{user}@{server}:{upload_relative_path}"

    command = [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        str(input_path.name),
        destination,
    ]

    try:
        log.info(f"Uploading {input_path.name} to {destination}")
        subprocess.run(
            command,
            check=True,
            capture_output=True,
        )
        log.info(f"Successfully uploaded {filename}")
    except subprocess.CalledProcessError as e:
        raise LagunaCamException(
            f"Unable to upload video. Command was: {e.cmd}. Exit code: {e.returncode}.\nError output: {e.stderr.decode()}"
        )
    finally:
        Path(input_path.name).unlink(missing_ok=True)

    return filename


def create_video_task(size=Arg("size"), duration=Arg("duration")):
    try:
        filename = record(width=size[0], height=size[1], duration=duration)
        filename = encode(filename)
        filename = upload(filename)
    except LagunaCamException as e:
        log.error(e)
    else:
        log.info(f"Successfully created {filename}")


if __name__ == "__main__":
    (
        log_level,
        interval,
        duration,
        size,
    ) = parse_args()

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H_%M_%S')
    logging.basicConfig(
        format='%(levelname)s:%(asctime)s %(message)s',
        datefmt='%m/%d/%Y %I:%M:%S %p',
        level=log_level,
    )
    log = logging.getLogger("lagunacam")
    handler = TimedRotatingFileHandler("lagunacam.log",
                                       when="m",
                                       interval=1,
                                       backupCount=5)
    log.addHandler(handler)
    

    app.params(
        size=size,
        duration=duration,
    )

    app.session.create_task(
        start_cond=interval, name="create a video", func=create_video_task
    )

    app.run()
