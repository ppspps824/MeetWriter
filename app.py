import datetime
import os
import threading
import time

import openai
import pyaudio
import PySimpleGUI as sg
import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()

SAMPLERATE = 44100
openai.api_key = os.environ.get("OPENAI_API_KEY")

audio = pyaudio.PyAudio()
stream = None
transcripts = []
summary = ""


def get_input_devices():
    devices = []
    for i in range(audio.get_device_count()):
        device = audio.get_device_info_by_index(i)
        if device["maxInputChannels"] > 0:  # 入力デバイスのみをリストに追加
            devices.append((device["name"], i))
    return devices


input_devices = get_input_devices()
layout = [
    [
        sg.Button("Start Recording"),
        sg.Button("Stop Recording", disabled=True),
        sg.Button("Setting"),
        sg.Button("Exit"),
        sg.Text("", size=(10, 1), justification="right", key="_TIMER_"),
    ],
    [sg.Output(size=(60, 10))],
    [sg.Text("Summary")],
    [sg.Multiline(size=(60, 10), key="-SUMMARY-", disabled=True)],
]
window = sg.Window("Speech Recognition App", layout, finalize=True)
recognizer = sr.Recognizer()


def show_timer():
    global recording_start_time, timer_active
    while timer_active:
        elapsed_time = time.time() - recording_start_time
        minutes, seconds = divmod(elapsed_time, 60)
        window.Element("_TIMER_").Update(
            "Rec:{:02}:{:02}".format(int(minutes), int(seconds))
        )
        time.sleep(1)


def get_recording_duration():
    if recording_start_time and recording_end_time:
        return recording_end_time - recording_start_time
    return 0


def save_transcripts_to_file():
    global transcripts, recording_start_time, recording_end_time

    now = datetime.datetime.now()
    now_format = now.strftime("%Y%m%d%H%M%S")

    start_time = datetime.datetime.fromtimestamp(recording_start_time)
    end_time = datetime.datetime.fromtimestamp(recording_end_time)

    filename = f"transcript_{now_format}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        duration = get_recording_duration()
        minutes, seconds = divmod(duration, 60)
        f.write(f"Start Time: {start_time}\n")
        f.write(f"End Time: {end_time}\n")
        f.write(f"Recording Duration: {int(minutes):02}:{int(seconds):02}\n\n")
        f.write("## Summary\n")
        f.write(summary + "\n")
        f.write("## Transcript\n")
        for transcript in transcripts:
            f.write(transcript + "\n")
    sg.popup(f"Saved successfully! : {filename}")


def callback(in_data, frame_count, time_info, status):
    global transcripts
    try:
        audiodata = sr.AudioData(in_data, SAMPLERATE, 2)
        sprec_text = recognizer.recognize_google(audiodata, language="ja-JP")
        transcripts.append(sprec_text)
        print(sprec_text)
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        pass
    finally:
        return (None, pyaudio.paContinue)


def send_messages(text):
    settings = "要約してください。途切れている部分や意味が通じない部分は前後の文脈から推測して補ってください。"
    messages = [
        {"role": "system", "content": settings},
        {"role": "user", "content": text},
    ]
    try_count = 3
    for try_time in range(try_count):
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
            )
            return resp
        except Exception as e:  # すべての例外を捕捉する一般的なExceptionを使用
            print(e)
            print(f"retry: {try_time + 1}/{try_count}")
            time.sleep(1)


def summarize_transcripts():
    global transcripts, summary
    while True:
        time.sleep(60)  # 1分ごとに要約
        if is_recording and transcripts:
            combined_text = " ".join(transcripts)
            response = send_messages(combined_text)
            summarized_text = response.choices[0]["message"].get("content", "")
            summary = summarized_text
            window["-SUMMARY-"].update(summary)


def start_recording():
    global stream, recording_start_time, timer_active, is_recording, selected_device_index

    if selected_device_index is None:
        selected_device_index = input_devices[0][1]

    transcripts = []
    stream = audio.open(
        format=pyaudio.paInt16,
        rate=SAMPLERATE,
        channels=1,
        input_device_index=selected_device_index,
        input=True,
        frames_per_buffer=SAMPLERATE * 10,
        stream_callback=callback,
    )
    stream.start_stream()
    recording_start_time = time.time()
    timer_active = True
    timer_thread = threading.Thread(target=show_timer)
    timer_thread.start()
    is_recording = True


def stop_recording():
    global stream, timer_active, recording_end_time, is_recording
    if stream:
        stream.stop_stream()
        stream.close()
        stream = None
    recording_end_time = time.time()
    timer_active = False
    is_recording = False


timer_active = False
recording_start_time = None
recording_end_time = None
is_recording = False
selected_device_index = None

summary_thread = threading.Thread(target=summarize_transcripts)
summary_thread.daemon = True
summary_thread.start()

while True:
    event, values = window.read()
    if event == sg.WINDOW_CLOSED or event == "Exit":
        stop_recording()
        break
    elif event == "Start Recording":
        start_recording()
        window["Start Recording"].update(disabled=True)
        window["Stop Recording"].update(disabled=False)
        window["Setting"].update(disabled=True)
    elif event == "Stop Recording":
        stop_recording()
        save_transcripts_to_file()
        window["Start Recording"].update(disabled=False)
        window["Stop Recording"].update(disabled=True)
        window["Setting"].update(disabled=False)
    elif event == "Setting":
        settings_layout = [
            [
                sg.Text("Input Device:"),
                sg.Combo(
                    [device[0] for device in input_devices],
                    default_value=input_devices[0][0]
                    if not selected_device_index
                    else [
                        device[0]
                        for device in input_devices
                        if device[1] == selected_device_index
                    ][0],
                    key="-DEVICE-",
                    size=(30, 1),
                ),
            ],
            [sg.Button("Save"), sg.Button("Cancel")],
        ]

        settings_window = sg.Window("Setting", settings_layout)

        while True:
            event_settings, values_settings = settings_window.read()

            if event_settings == sg.WINDOW_CLOSED or event_settings == "Cancel":
                break
            elif event_settings == "Save":
                selected_device_name = values_settings["-DEVICE-"]
                selected_device_index = next(
                    (
                        device[1]
                        for device in input_devices
                        if device[0] == selected_device_name
                    ),
                    None,
                )
                break

        settings_window.close()

window.close()
