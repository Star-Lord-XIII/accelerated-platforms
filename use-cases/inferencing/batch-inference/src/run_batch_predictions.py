# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import logging.config
import os
import signal
import sys

import pandas as pd
import requests
from datasets import load_from_disk
from google.cloud import storage


def graceful_shutdown(signal_number, stack_frame):
    signal_name = signal.Signals(signal_number).name
    logger.info(f"Received {signal_name}({signal_number}), shutting down...")
    sys.exit(0)


class Batch_Inference:
    def __init__(self):
        self.api_endpoint = os.environ["ENDPOINT"]          # e.g. http://host/v1/audio/transcriptions
        self.model_name = os.environ["MODEL_PATH"]          # e.g. openai/whisper-large-v3
        self.output_file = os.environ["PREDICTIONS_FILE"]
        self.gcs_bucket = os.environ["BUCKET"]
        self.dataset_output_path = os.environ["DATASET_OUTPUT_PATH"]

        test_dataset = load_from_disk(
            f"gs://{self.gcs_bucket}/{self.dataset_output_path}/test"
        )
        self.test_df = test_dataset.to_pandas()
        self.df = pd.concat([self.test_df], axis=0)
        self.df.reset_index(drop=True, inplace=True)

    def predict(self):
        logger.info("Start predictions")

        for i in range(len(self.df)):
            # --- Whisper expects an audio file path, not a text prompt ---
            audio_path = self.df["audio_path"][i]   # column holding local/gs path to audio

            # If your dataset stores raw audio bytes in an "audio" dict (HF AudioDataset),
            # write them to a temp file first:
            # audio_bytes = self.df["audio"][i]["bytes"]
            # audio_path  = f"/tmp/sample_{i}.wav"
            # with open(audio_path, "wb") as tmp: tmp.write(audio_bytes)

            if not os.path.exists(audio_path):
                logger.warning(f"Audio file not found, skipping: {audio_path}")
                continue

            # --- Whisper / OpenAI-compatible transcription request ---
            with open(audio_path, "rb") as audio_file:
                files = {"file": (os.path.basename(audio_path), audio_file, "audio/wav")}
                data  = {
                    "model": self.model_name,           # "openai/whisper-large-v3"
                    "language": "en",                   # remove to auto-detect
                    "response_format": "json",          # or "text", "verbose_json"
                    "temperature": 0.0,
                }
                response = requests.post(self.api_endpoint, files=files, data=data)

            if response.status_code == 200:
                response_data = response.json()
                # OpenAI /v1/audio/transcriptions returns {"text": "..."}
                transcription = response_data["text"]

                logger.info(
                    f"HTTP {response.status_code} received",
                    extra={
                        "transcription": transcription,
                        "audio_path": audio_path,
                    },
                )

                with open(self.output_file, "a") as f:
                    f.write(transcription + "\n")
                    f.write("----------\n")
            else:
                logger.error(
                    f"Error for {audio_path}: {response.status_code} - {response.text}"
                )

        logger.info("Finish predictions")

        logger.info("Start write predictions to GCS")
        model_iteration_tag = self.model_name.rsplit("-", 1)[1]   # "v3"
        client = storage.Client()
        bucket = client.get_bucket(self.gcs_bucket)
        with open(self.output_file, "r") as local_file:
            blob = bucket.blob(f"predictions/{self.output_file}-{model_iteration_tag}")
            blob.upload_from_file(local_file)
        logger.info("Finish write predictions to GCS")

    def batchType(self):
        if "ACTION" in os.environ and os.getenv("ACTION") == "predict":
            self.predict()


if __name__ == "__main__":
    logging.config.fileConfig("logging.conf")
    logger = logging.getLogger("batch_inference")

    if "LOG_LEVEL" in os.environ:
        new_log_level = os.environ["LOG_LEVEL"].upper()
        logger.info(f"Log level set to '{new_log_level}' via LOG_LEVEL environment variable")
        logging.getLogger().setLevel(new_log_level)
        logger.setLevel(new_log_level)

    logger.info("Configure signal handlers")
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    inference = Batch_Inference()
    inference.batchType()
