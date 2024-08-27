import tkinter as tk
from tkinter.ttk import Progressbar, Frame
from tkinter import filedialog, messagebox, simpledialog
import cv2
from PIL import Image, ImageTk
import os
import sort_openpose_output, movements
import subprocess
import threading
import time
import tempfile
import shutil
import re

cpu = False
fpsGlobal = -1
threshold = 0.3
goAnalyze = False
threads = []
left = True
right = True

class cd:
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        self.newPath = os.path.expanduser(newPath)

    def __enter__(self):
        self.savedPath = os.getcwd()
        os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.savedPath)


class SettingsGUI:
    '''Small GUI for the settings screen before analyzing.'''
    def __init__(self, master):
        self.master = master
        self.open = True  # indicates if the settings screen is open
        self.master.title("Settings")
        master.iconphoto(False, tk.PhotoImage(file='./GUI/spudnig.png'))  # Use .png instead of .ico for Linux
        self.completed = False
        self.cancelled = False

        tk.Label(master, text="Frames per second (fps):").grid(row=0)
        tk.Label(master, text="Reliability threshold:").grid(row=1)

        self.e1 = tk.Entry(master)
        self.e1.insert(0, str(fpsGlobal))
        self.e2 = tk.Entry(master)
        self.e2.insert(0, str(0.3))

        self.checkLeft = tk.IntVar()
        self.checkRight = tk.IntVar()
        self.c1 = tk.Checkbutton(master, text="Left hand", variable=self.checkLeft, onvalue=1, offvalue=0)
        self.c2 = tk.Checkbutton(master, text="Right hand", variable=self.checkRight, onvalue=1, offvalue=0)
        self.c1.select()
        self.c2.select()

        self.e1.grid(row=0, column=1)
        self.e2.grid(row=1, column=1)

        self.c1.grid(row=2, column=0)
        self.c2.grid(row=2, column=1)

        self.ok = tk.Button(master, text="OK", command=self.apply)
        self.ok.grid(row=3, column=0)

        self.cancel = tk.Button(master, text="Cancel", command=self.cancelSettings)
        self.cancel.grid(row=3, column=1)
        self.master.protocol("WM_DELETE_WINDOW", self.cancelSettings)

        # Thread closes settings screen when open for too long
        closeSettingsThread = threading.Thread(target=self.shutDown)
        closeSettingsThread.start()
        threads.append(closeSettingsThread)

    def cancelSettings(self):
        '''Closes the settings screen by clicking cancel button'''
        self.open = False
        self.cancelled = True
        self.master.destroy()

    def apply(self):
        '''Function that is called when OK button in settings screen is clicked.'''
        global threshold
        global fpsGlobal
        global goAnalyze
        global left, right

        # Check input for reliability settings
        threshold = self.e2.get()
        if not re.search(r"[0]\.[1-9]", threshold):
            self.open = False
            self.cancelled = True
            self.master.destroy()
            tk.messagebox.showerror("Invalid number", "The reliability threshold should be a decimal between 0-1 split by a dot (e.g. 0.3).")
            return

        threshold = float(threshold)
        fpsGlobal = int(self.e1.get())

        if self.checkLeft.get() == 0:
            left = False
        if self.checkRight.get() == 0:
            right = False

        goAnalyze = True
        self.master.destroy()
        self.open = False
        self.completed = True

    def shutDown(self):
        '''Shuts down settings screen when open for too long.'''
        must_end = time.time() + 600
        while time.time() < must_end:
            if not self.open:
                break
            time.sleep(0.25)

        if self.open:
            self.master.destroy()
            messagebox.showerror("Error", "You timed out. Please click Analyze again if you want to analyze the video.")
            return
        else:
            return


class GUI:
    '''GUI for the application.'''
    def __init__(self, master):
        self.master = master
        self.tempDir = tempfile.mkdtemp()
        print(self.tempDir)
        print("working")
        self.master.title("SPUDNIG")
        self.readyForAnalysis = False
        self.workdir = os.getcwd()
        master.iconphoto(False, tk.PhotoImage(file='./GUI/spudnig.png'))  # Use .png instead of .ico for Linux

        if cpu:
            self.openpose = os.path.join(self.workdir, "openpose_cpu/bin/OpenPoseDemo")
        else:
            self.openpose = os.path.join(self.workdir, "/openpose/build/examples/openpose.bin")

        self.data = None
        self.fps = fpsGlobal
        self.finished = False
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)

        self.frame = tk.Frame(master)
        self.frame.pack()

        self.menu = tk.Menu(self.frame)
        self.file_expand = tk.Menu(self.menu, tearoff=0)
        self.file_expand.add_command(label='New...', command=self.newFile)
        self.file_expand.add_command(label='Open...', command=self.openVideo)
        self.file_expand.add_command(label='Save as...', command=self.saveFile)
        self.file_expand.add_command(label='About', command=self.showAbout)
        self.menu.add_cascade(label='File', menu=self.file_expand)
        self.master.config(menu=self.menu)

        self.welcome = tk.Label(self.frame,
                                text="Welcome to SPUDNIG. Select a file to analyze via File -> Open...")
        self.welcome.pack(pady=20)

        self.bottomframe = tk.Frame(self.master)
        self.bottomframe.pack(side=tk.BOTTOM)

        self.analyzeButton = tk.Button(self.bottomframe, text='Analyze', command=self.analyzeButtonClicked)
        self.analyzeButton.pack(side=tk.BOTTOM, pady=20)
        self.analyzeButton.configure(font=('Sans', '13', 'bold'), background='red2')

        self.progress = Progressbar(self.bottomframe, length=200, orient=tk.HORIZONTAL, mode='determinate')
        self.progress['value'] = 0
        self.barLabel = tk.Label(self.bottomframe, text='Analyzing...', font='Bold')

        global left, right
        left = True
        right = True

    def saveFile(self):
        '''Saves the Elan importable file at a location selected by the user.'''
        if self.finished:
            self.saved = False
            self.savefile = filedialog.asksaveasfilename(initialdir="/", title="Save file", filetypes=(("csv files", "*.csv"), ("all files", "*.*")))
            if self.savefile is None:
                return
            else:
                if not self.savefile.endswith(".csv"):
                    self.savefile += ".csv"
                self.data.to_csv(self.savefile)
                self.saved = True
                # TODO: delete files
                shutil.rmtree(self.outputfoler, ignore_errors=True)
                os.remove('hand_left_sample.csv')
                os.remove('hand_right_sample.csv')
                os.remove('sample.csv')
        else:
            tk.messagebox.showerror("No file", "There's nothing to save yet.")

    def newFile(self):
        '''Opens a new window after the new button is clicked.'''
        input = tk.messagebox.askokcancel("Warning", "Opening a new window will close the old one and unsaved data will be lost.")
        if input:
            shutil.rmtree(self.tempDir)
            self.master.destroy()

            newWindow = tk.Tk()
            newWindow.geometry('1000x750')
            new_gui = GUI(newWindow)
            newWindow.mainloop()

    def showAbout(self):
        tk.messagebox.showinfo("About SPUDNIG", "SPeeding Up the Detection of Non-iconic and Iconic Gestures (SPUDNIG) is a toolkit for the"
                               + " automatic detection of hand movements and gestures in video data. \n\nIt is developed by Jordy Ripperda, a MSc"
                               + " student in Artificial Intelligence at the Radboud University in Nijmegen (Netherlands). This toolkit was"
                               + " developed during my thesis project at the Max Planck Institute for Psycholinguistics also in Nijmegen.")

    def openVideo(self):
        '''Starts thread for opening video.'''
        self.filename = filedialog.askopenfilename(initialdir='/', title='Select file', filetypes=(("avi files", ".avi"), ("all files", "*.*")))
        if self.filename:
            openVidThread = threading.Thread(target=self.openVideoThread)
            openVidThread.start()
            threads.append(openVidThread)

    def openVideoThread(self):
        '''Opens the video when open... button is clicked and shows a screenshot of a frame from the video'''
        # Read videofile
        cap = cv2.VideoCapture(self.filename)
        self.totalFrames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        self.width = int(cap.get(3))
        self.height = int(cap.get(4))
        cap.set(1, int(self.totalFrames // 2))  # Set video frame to frame in the middle
        ret, frame = cap.read()
        cap.release()
        cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        self.img = Image.fromarray(cv2image)
        imgtk = ImageTk.PhotoImage(image=self.img)

        if hasattr(self, 'panel'):
            self.panel.configure(image=imgtk)
            self.panel.image = imgtk
        else:
            self.panel = tk.Label(image=imgtk)
            self.panel.image = imgtk
            self.panel.pack()

        self.readyForAnalysis = True
        self.welcome.pack_forget()

    def analyzeButtonClicked(self):
        '''Shows settings screen when analyze button is clicked.'''
        if not self.readyForAnalysis:
            tk.messagebox.showerror("File not ready", "Please select a video first.")
            return

        self.settingsScreen = tk.Tk()
        self.settingsGUI = SettingsGUI(self.settingsScreen)
        self.settingsScreen.mainloop()

        if goAnalyze:
            self.progress.pack()
            self.barLabel.pack()
            analyzeThread = threading.Thread(target=self.analyze)
            analyzeThread.start()
            threads.append(analyzeThread)

    def analyze(self):
        '''Analyzes the video using the OpenPoseDemo'''
        global threshold
        global fpsGlobal

        if not os.path.exists(self.tempDir):
            os.makedirs(self.tempDir)
        self.outputfolder = os.path.join(self.tempDir, "output/")

        if not os.path.exists(self.outputfolder):
            os.makedirs(self.outputfolder)

        self.detection_command = [self.openpose, "--video", self.filename, "--hand", "--write_json",
                                  self.outputfolder, "--display", "0", "--render_pose", "0",
                                  "--frame_step", str(int(round(self.fps / fpsGlobal)))]
        if not left:
            self.detection_command.append("--disable_blending_left")
        if not right:
            self.detection_command.append("--disable_blending_right")

        self.update_progress(10)

        # Use subprocess to run the detection command
        with cd(self.workdir):
            try:
                detection_proc = subprocess.Popen(self.detection_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out, err = detection_proc.communicate()
                if detection_proc.returncode != 0:
                    raise Exception(f"Error in OpenPose processing: {err.decode('utf-8')}")
            except Exception as e:
                tk.messagebox.showerror("OpenPose Error", str(e))
                return

        self.update_progress(70)

        # Process output
        try:
            self.data = sort_openpose_output.sort(self.outputfolder, threshold)
            self.update_progress(100)
        except Exception as e:
            tk.messagebox.showerror("Processing Error", f"Error processing OpenPose output: {str(e)}")
            return

        self.finished = True
        tk.messagebox.showinfo("Analysis Complete", "Analysis is complete. You can now save the results.")

    def update_progress(self, value):
        self.progress['value'] = value
        self.master.update_idletasks()

    def on_close(self):
        '''Handles application closing event'''
        if hasattr(self, 'outputfolder'):
            shutil.rmtree(self.outputfolder, ignore_errors=True)
        shutil.rmtree(self.tempDir)
        self.master.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry('1000x750')
    gui = GUI(root)
    root.mainloop()
