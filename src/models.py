import os
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from loguru import logger
from utils import convert_to_formats
import deepl
from deepl_languages import (
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
)  # TODO: change this to the correct path from JSON file /static/supported_languages_TR.json


from dotenv import load_dotenv
from db import transcriptionsDB
import time

# Load the API keys
load_dotenv()  # Load the environment variables: HUGGINGFACE_API_KEY and DEEPL_API_KEY

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")

# Define the Hugging Face available models
MODELS = {
    "whisper_tiny": "openai/whisper-tiny",
    "whisper_base": "openai/whisper-base",
    "whisper_small": "openai/whisper-small",
    "whisper_medium": "openai/whisper-medium",
    "whisper_large": "openai/whisper-large-v3",
    "m4t_medium": "facebook/seamless-m4t-medium",
    "m4t_large": "facebook/seamless-m4t-v2-large",
}

DEFAULT_MODEL = "whisper_base"

device = "cuda:0" if torch.cuda.is_available() else "cpu"
torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..\output")

DB = transcriptionsDB(os.path.join(OUTPUT_DIR, "transcriptions.db"))


def transcribe_audio(
    file_path: str,
    language: str,
    model: str,
    translation: str,
    language_translation: str,
    pid: int,
):
    """
    Transcribe the audio using Hugging Face models
    Args:
        file_path (str): Path to the audio file
        language (str): Language of the audio
        model (str): The transcription model to use
        translation (str): The translation model to use
        language_translation (str): The language to translate the transcription to
        file_export (str): The file format to export the transcription
    """

    logger.info(
        f"Transcribing audio using model: {model}, language: {language}, translation: {translation}, language_translation: {language_translation}"
    )

    # If file path is empty, return
    if not file_path:
        # update_transcription_status({"phase": "Error", "progress": 0})
        logger.error("No file path provided. Progress: 0%")
        DB.update_transcription_status_by_pid(
            "Error:No file path provided.", "", 0, pid
        )
        return

    stt_model = MODELS.get(model)

    # Check if the model is valid
    if not stt_model:
        # update_transcription_status({"phase": "Error", "progress": 0})
        logger.error(f"Invalid model: {model}. Progress: 0%")
        DB.update_transcription_status_by_pid("Error:Invalid model.", "", 0, pid)
        return

    try:

        logger.info(
            f"Transcribing audio phase: Loading model and processor... . Progress: 30%"
        )
        DB.update_transcription_status_by_pid(
            "Loading transcription model...", "", 30, pid
        )

        # Load the model and processor
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            stt_model,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        )
        model.to(device)

        processor = AutoProcessor.from_pretrained(stt_model)

        logger.info(f"Transcribing audio phase: Transcribing... Progress: 40%")
        DB.update_transcription_status_by_pid("Transcribing...", "", 40, pid)

        if language == "auto":
            pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                max_new_tokens=128,
                chunk_length_s=30,
                batch_size=16,
                return_timestamps=True,
                torch_dtype=torch_dtype,
                device=device,
            )
        else:
            pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                max_new_tokens=128,
                chunk_length_s=30,
                batch_size=16,
                return_timestamps=True,
                torch_dtype=torch_dtype,
                device=device,
                generate_kwargs={"language": language},
            )

        # Transcribe the audio file
        transcription_result = pipe(file_path)

        logger.info(
            f"Transcribing audio phase: Saving transcription... . Progress: 70%"
        )
        DB.update_transcription_status_by_pid("Saving transcription...", "", 70, pid)

        # Extract text and timestamps
        transcription = ""
        for chunk in transcription_result["chunks"]:
            start_time = chunk["timestamp"][0]
            end_time = chunk["timestamp"][1]
            text = chunk["text"]
            transcription += f"{start_time} --> {end_time}\n{text}\n\n"

        logger.info(f"Transcribing audio phase: Transcription saved. Progress: 80%")
        DB.update_transcription_status_by_pid("Transcription saved", "", 80, pid)

        # Check if translation is needed
        if translation and language != language_translation:

            if translation is None:
                logger.info(f"Do not have a translation model. Skipping translation.")
            elif translation == "whisper":
                # TODO: Implement whisper translation here
                logger.info(
                    f"Translating from {language} to {language_translation} using whisper."
                )
                pass
            else:
                # update_transcription_status({"phase": "Translating..."})
                logger.info(f"Transcribing audio phase: Translating... . Progress: 85%")
                DB.update_transcription_status_by_pid("Translating...", "", 85, pid)
                logger.info(f"Translating from {language} to {language_translation}")
                source_lang = SOURCE_LANGUAGES.get(language.upper())
                target_lang = TARGET_LANGUAGES.get(language_translation.upper())
                if not source_lang or not target_lang:
                    raise ValueError(
                        f"Invalid language code: {language} or {language_translation}"
                    )
                transcription = deepl_translate(
                    transcription,
                    source_lang,
                    target_lang,
                    pid,
                )

        # Save the transcription to a file
        # output_file = file_path.rsplit(".", 1)[0] + f".{file_export}"

        # Save the transcription files on a folder with the process ID
        # Generate the output folder
        if not os.path.exists(OUTPUT_DIR + f"\\{pid}"):
            os.makedirs(OUTPUT_DIR + f"\\{pid}")

        output_file = os.path.join(OUTPUT_DIR, f"{pid}\\transcription.txt")
        with open(output_file, "w") as f:
            f.write(transcription)

        logger.info(
            f"Transcribing audio phase: Exporting transcription... . Progress: 90%"
        )
        DB.update_transcription_status_by_pid("Exporting transcription...", "", 90, pid)

        # convert_to_formats(transcription, file_path.rsplit(".", 1)[0], file_export)

        convert_to_formats(transcription, output_file, "all")

        logger.info(f"Transcribing audio phase: Completed successfully! Progress: 100%")
        DB.update_transcription_status_by_pid(
            "Completed successfully!", str(time.time()), 100, pid
        )

    except Exception as e:
        # update_transcription_status({"phase": "Error", "progress": 0})
        logger.error(f"Transcription failed: {str(e)}. Progress: 0%")
        DB.update_transcription_status_by_pid("Error", "", 0, pid)


def deepl_translate(text: str, source_lang: str, target_lang: str, pid: int):
    """
    Translate the text using DeepL API
    Args:
        text (str): Text to translate
        source_lang (str): Source language of the text
        target_lang (str): Target language for translation
        pid (int): The process ID
    Returns:
        str: Translated text
    """

    logger.info(f"Translating text from {source_lang} to {target_lang}")

    try:
        translator = deepl.Translator(DEEPL_API_KEY)
        result = translator.translate_text(
            text, source_lang=source_lang.upper(), target_lang=target_lang.upper()
        )
        return result.text
    except Exception as e:
        # update_transcription_status({"phase": "Translation Error", "progress": 0})
        logger.error(f"Translation failed: {str(e)}. Progress: 0%")
        DB.update_transcription_status_by_pid("Translation Error", "", 0, pid)
        return text
