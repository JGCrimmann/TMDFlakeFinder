"""TMDFlakeFinder

Authors: Juri G. Crimmann, Moritz N. Junker, Yannik M. Glauser, Nolan Lassaline, Gabriel Nagamine, and David J. Norris
Date: 2024 May 10th
License: CC BY-NC-SA 4.0
Description: The program automatically identifies TMD flakes.

"""

from PyQt5.QtWidgets import *
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import (Qt,
                          QObject,
                          QThread,
                          pyqtSignal
                          )
from PyQt5.QtWidgets import (QApplication,
                             QWidget, 
                             QInputDialog,
                             QLineEdit,
                             QFileDialog,
                             QMessageBox,
                             QSlider
                             )
import pandas as pd
import numpy as np
import time
import random
from pylablib.devices import Thorlabs
from pylablib.devices import uc480
import matplotlib
import matplotlib.pyplot as plt
from matplotlib_scalebar.scalebar import ScaleBar
from PIL import Image
import cv2
import csv 
from tqdm import tqdm
import math
import statistics
import os
import pathlib
from datetime import datetime, timedelta
from itertools import cycle, islice



class MyThread(QThread):
    """Creates a separate thread which counts from 0 to 100 for smooth progress bar display."""
    change_value = pyqtSignal(int)
    def run(self):
        cnt = 0
        while cnt < 100:
            cnt+=1
            time.sleep(0.3)
            self.change_value.emit(cnt)


class HomingThread(QObject):
    """Creates a separate thread for the process of homing the stage."""
    finished = pyqtSignal()
    statusUpdate = pyqtSignal(str)
    
    def run(self):
        '''Both x- and y-stages are initiated and homed separately.'''
        with Thorlabs.KinesisMotor('27261747') as stage_y, \
                Thorlabs.KinesisMotor('27261810') as stage_x:
            self.statusUpdate.emit('Start homing stage.')
            stage_x.setup_velocity(acceleration=50000, max_velocity=50000)
            stage_y.setup_velocity(acceleration=50000, max_velocity=50000)
            stage_x.move_to(0)
            stage_x.wait_move()
            stage_y.move_to(0)
            stage_y.wait_move()
            self.statusUpdate.emit('Homing in process...')
            stage_x.home(force=True)
            self.statusUpdate.emit('X-stage is now homed.')
            stage_y.home(force=True)
            self.statusUpdate.emit('Y-stage is now homed.')
            stage_x.wait_for_home()
            stage_y.wait_for_home()    
            self.statusUpdate.emit('Homing was successful.')
        self.finished.emit()


class GridscanThread(QObject):
    """Creates the main separate thread where the grid scan is running."""
    finished = pyqtSignal()
    refresh_flakelist = pyqtSignal(str)
    statusUpdate = pyqtSignal(str)
    timeUpdate = pyqtSignal(object)
    change_value = pyqtSignal(int)
    flush_listwidget = pyqtSignal()
    
    ### Scan Variables 
    conversion_umstep = 300/8.6818
    x_increment = 18800  # steps
    y_increment = 14100  # steps


    ### Gridscan functions
    def set_camera_settings(self):
        '''Defines camera settings such as pixel rate, gains, exposure, etc.'''
        self.cam.set_device_variable('pixel_rate', 1E6)  # Pixel clock = 5 MHz
        self.cam.set_device_variable('frame_period', 1)
        self.cam.set_device_variable('gain_boost', False)
        self.cam.set_device_variable('gains', (4, 1, 1, 1))
        self.cam.set_exposure(0.2)
        self.statusUpdate.emit('Camera settings set.')
        print('set_camera_settings executed!')
             
    def set_stage_velocity(self, vel=50000):
        '''Sets stage velocity and acceleration.'''
        self.stage_x.setup_velocity(acceleration=vel, max_velocity=vel)
        self.stage_y.setup_velocity(acceleration=vel, max_velocity=vel)
        self.statusUpdate.emit(f'Stage velocity set to {vel}.')
        print('set_stage_velocity executed!')
            
    def move_to_origin(self):
        '''Moves stage to origin (0|500). Y-origin is not set at 0, since that causes malfunction of the stage for the first increment during grid scan.
        '''
        self.statusUpdate.emit('Moving stage to origin.')
        self.stage_x.move_to(0)
        self.stage_y.move_to(500*GridscanThread.conversion_umstep)
        self.stage_x.wait_move()
        self.stage_y.wait_move()
        self.statusUpdate.emit('Stage is now at origin (0|0).')
        print('move_to_origin executed!')

    def create_new_dir(self):
        '''Creates a new directory to store scan data and returns the folder name. Grid_Scans_WSe2BilayerScript folder has to exist already!
        '''
        today = datetime.now()
        directory_name = today.strftime('%y%m%d') + '_' + today.strftime('%H_%M')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}/flakes')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}/flakes/uncropped')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}/flakes/highlighted')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}/flakes/zoomed')
        os.mkdir(f'Grid_Scans_WSe2BilayerScript/{directory_name}/all_images')
        
        # self.abs_path = f'C:/Users/spadmin/Documents/Grid_Scans_WSe2BilayerScript/{directory_name}'
        self.statusUpdate.emit(f'New directory created at \t\t\t[Grid_Scans_WSe2BilayerScript/{directory_name}]')
        return directory_name

    def define_scan_coords(self):
        '''Returns a list of (x|y) coordinate tuples, which define the to be scanned grid.
        '''    
        coordinates = list()
        x_steps = (math.floor(12000
                   / (GridscanThread.x_increment 
                   / GridscanThread.conversion_umstep)))
        y_steps = math.floor(12000 
                   / (GridscanThread.y_increment
                   / GridscanThread.conversion_umstep))
        for y in range(y_steps+1):
            if y%2 == 0:
                for x in range(x_steps+1):
                    coordinates.append((GridscanThread.x_increment*x, GridscanThread.y_increment*y + 500*GridscanThread.conversion_umstep))
            else:
                for x in range(x_steps, -1, -1):
                    coordinates.append((GridscanThread.x_increment*x, GridscanThread.y_increment*y + 500*GridscanThread.conversion_umstep))
        self.statusUpdate.emit(f'Grid scan dimensions: ({x_steps+1}x{y_steps+1})')
        print('define_scan_coords executed!')
        return coordinates
    
    def dynamic_threshold(self):
        """The image threshold for flagging flakes is dynamically determined by capturing five images. Each image is filtered with a gaussian filter to remove spot noise or dead pixels and then the largest grey value of the image is determined and stored in a list. The median score (more robust towards outliers) is selected and 15 is added to that value in order to have some margin for misclassification.
        """
        self.statusUpdate.emit('Determining threshold value for flake detection')
        maxScores = list()
        runtime = list()
        for coord in self.scan_coords[:5]:
            tic = datetime.now()
            self.stage_x.move_to(coord[0])
            self.stage_y.move_to(coord[1])
            self.stage_x.wait_move()
            self.stage_y.wait_move()
            
            img_gaussian = cv2.GaussianBlur(self.cam.snap(),(9,9),0)
            maxScores.append(np.max(img_gaussian))
            tac = datetime.now()
            runtime.append(tac-tic)
            
        threshold = statistics.median(maxScores) + 5
        median_runtime = statistics.median(runtime) + timedelta(seconds=1)
        self.statusUpdate.emit(f'Threshold value set at: {threshold}')
        return threshold, median_runtime
        
    def snap_and_process_image(self):
        """An image is taken and the position on the grid is stored as an object of the Images class. All these objects are stored as list elements of images_list. A gaussian filter is applied to the image and the number of pixels exceeding the threshold is computed. The image is flagged as a flake if more than 100 pixels in the image exceed the threshold and then the image is saved. The maxLoc function determines the coordinates of the brightest pixel and allows cropping the flake. 
        """
        
        time.sleep(0.1)
        ### Capture Image
        self.images_list.append(Images(self.cam.snap(), Images.img_counter, self.stage_x.get_position(), self.stage_y.get_position()))
        ### Apply Gaussian Blur 
        img_gaussian = cv2.GaussianBlur(self.images_list[-1].numpy_img,
                                        (9,9), 0)
        ### Analyse image if it contains any flakes.
        score = np.sum(img_gaussian > self.threshold)
        self.images_list[-1].score = score
        if score > 100:
            self.images_list[-1].flake_tag = True
            print('Flake found!')
        ### Determine flake location on the image
        (min_Val, maxVal, minLoc, maxLoc) = cv2.minMaxLoc(img_gaussian)
        self.images_list[-1].flake_loc_x = maxLoc[0]
        self.images_list[-1].flake_loc_y = maxLoc[1]        
        
        # Save Image without Scalebar
        
        img_save = Image.fromarray(self.images_list[-1].numpy_img)
        dims = img_save.size
        fig, axs = plt.subplots(figsize=(dims[0]/100,dims[1]/100), dpi=100)
            #Set the subplot parameters to have no padding
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            
        axs.imshow(img_save, cmap='gray', vmin=0, vmax=255)
        axs.axis('off')        
        fig.savefig(f'Grid_Scans_WSe2BilayerScript/{self.directory_name}/all_images/mono_10x_{self.images_list[-1].img_counter}.jpg', dpi = 100)
        plt.close(fig)        
        
        # Processing Flakes
        if self.images_list[-1].flake_tag == True:
            plt.close()
            # Add scalebar to picture
            fig, axs = plt.subplots(figsize=(dims[0]/100,dims[1]/100), dpi=100)
            #Set the subplot parameters to have no padding
            fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            
            axs.imshow(img_save, cmap='gray', vmin=0, vmax=255)
            axs.axis('off')        
            scalebar = ScaleBar(0.422, 'um', length_fraction=0.2,    
                                frameon=False, location='lower right', color='white', pad=0.7,
                                font_properties={'size':15})
            axs.add_artist(scalebar)
            
            fig.savefig(f'Grid_Scans_WSe2BilayerScript/{self.directory_name}/flakes/uncropped/mono_10x_{self.images_list[-1].img_counter}.jpg', dpi = 100)
            plt.close(fig)
            
           
            # Save Cropped Image with Scalebar
            def crop_center(pil_img, maxLoc, crop):
                return pil_img.crop(((maxLoc[0] - crop),
                                     (maxLoc[1] - crop*0.8),
                                     (maxLoc[0] + crop),
                                     (maxLoc[1] + crop*0.8)))

            img_zoomed = np.array(crop_center(img_save, maxLoc, crop=200))
            
            fig, axs = plt.subplots(figsize=(dims[0]/100,dims[1]/100), dpi=100)
            #Set the subplot parameters to have no padding
            fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            axs.imshow(img_zoomed, cmap='gray', vmin=0, vmax=255)
            axs.axis('off')        
            scalebar = ScaleBar(0.422, 'um', length_fraction=0.25, frameon=False, 
                                location='lower right', color='white', pad=0.7,
                                font_properties={'size':15})
            axs.add_artist(scalebar)
            
            fig.savefig(f'Grid_Scans_WSe2BilayerScript/{self.directory_name}/flakes/zoomed/mono_10x_{self.images_list[-1].img_counter}.jpg', dpi = 100)
            plt.close(fig)
            
            # Save Adittional Image with Highlighted Bilayers
            
            img_highlighted = np.zeros_like(img_save)  # Initialize the image as an array of zeros
            img_highlighted[(img_save >= self.threshold) & (img_save <= (self.threshold + 23))] = 255  # Set the pixels between threshold and threshold+10 to 255
            fig, axs = plt.subplots(figsize=(dims[0]/100, dims[1]/100), dpi=100)
            fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            axs.imshow(img_highlighted, cmap='gray', vmin=0, vmax=255)
            axs.axis('off')
            scalebar = ScaleBar(0.422, 'um', length_fraction=0.2,    
                                frameon=False, location='lower right', color='white', pad=0.7,
                                font_properties={'size':15})
            axs.add_artist(scalebar)
            
            fig.savefig(f'Grid_Scans_WSe2BilayerScript/{self.directory_name}/flakes/highlighted/bi_10x_{self.images_list[-1].img_counter}.jpg', dpi = 100)
            plt.close(fig)
            
        
        with open(f'./Grid_Scans_WSe2BilayerScript/{self.directory_name}/image_data.csv', 'w') as stream:
            writer = csv.writer(stream)
            writer.writerow(['img_count', 'x_pos', 'y_pos', 'flake_tag', 'score', 'flake_loc_x', 'flake_loc_y'])
            writer.writerows(self.images_list)
            
        if self.images_list[-1].flake_tag == True:
            self.refresh_flakelist.emit(self.directory_name)

    def run(self):
        """The main grid scan loop is executed, where stage and camera are initiated, a new directory is created, threshold is determined and an image is recorded and analysed at every position of the grid.
        """
        ### Initialize Camera
        print('Run gridscan executed!')
        self.cam = uc480.UC480Camera(cam_id=1)
        
        self.flush_listwidget.emit()

        ### Camera Settings 
        self.set_camera_settings()
        self.images_list = list()

        ### Initialize Stage
        with Thorlabs.KinesisMotor('27261747') as self.stage_y, \
             Thorlabs.KinesisMotor('27261810') as self.stage_x:
                  
            self.set_stage_velocity(vel=50000)

            self.move_to_origin()

            self.directory_name = self.create_new_dir()    
            
            self.scan_coords = self.define_scan_coords()
            
            self.threshold, self.runtime = self.dynamic_threshold()
                        
            self.statusUpdate.emit('Starting GridScan...')
            for n, coord in enumerate(self.scan_coords):
                self.stage_x.move_to(coord[0])
                self.stage_x.wait_move()
                self.stage_y.move_to(coord[1])
                self.stage_y.wait_move()

                self.snap_and_process_image()

                self.change_value.emit(round((n*100)/len(self.scan_coords)))
                self.timeUpdate.emit((len(self.scan_coords)-n)*(self.runtime))
        self.cam.close()
        self.statusUpdate.emit('Grid scan complete!')
        
       
        
class Images(GridscanThread):
    """Class to create the Images object where all relevant information about the imgage is stored. 
    """
    img_counter = 0
    flake_loc_x = None # Flake location on the image itself in px
    flake_loc_y = None # Flake location on the image itself in px
    
    def __init__(self, numpy_img, img_counter, x_pos, y_pos):
        self.numpy_img = numpy_img
        self.img_counter = img_counter
        Images.img_counter += 1
        self.x_pos = x_pos
        self.y_pos = y_pos
        self.flake_tag = False
        
    def __iter__(self):
        return iter([self.img_counter, self.x_pos, self.y_pos, self.flake_tag,
                     self.score, self.flake_loc_x, self.flake_loc_y])


class Ui_MainWindow(object):
    """Class which contains all GUI (Graphical User Interface) elements."""
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1175, 900)
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        
        # Flake image "label"
        self.uncropped_flake_box = QtWidgets.QLabel(self.centralwidget)
        self.uncropped_flake_box.setGeometry(QtCore.QRect(127, 451, 499, 391))
        self.uncropped_flake_box.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.uncropped_flake_box.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.uncropped_flake_box.setLineWidth(4)
        self.uncropped_flake_box.setText("")
        # self.uncropped_flake_box.setPixmap(QtGui.QPixmap("../17062022_12_11/flakes/uncropped_sb_flakes/mono_10x_flake_316.jpg"))
        self.uncropped_flake_box.setScaledContents(True)
        self.uncropped_flake_box.setIndent(-1)
        self.uncropped_flake_box.setObjectName("uncropped_flake_box")
        
        ### Flake list widget
        self.flake_list = QtWidgets.QListWidget(self.centralwidget)
        self.flake_list.setGeometry(QtCore.QRect(17, 451, 101, 391))
        self.flake_list.setMouseTracking(False)
        self.flake_list.setDragDropMode(QtWidgets.QAbstractItemView.NoDragDrop)
        self.flake_list.setObjectName("flake_list")
        self.flake_list.itemSelectionChanged.connect(self.selectionChanged)
        
        self.flake_image_label = QtWidgets.QLabel(self.centralwidget)
        self.flake_image_label.setGeometry(QtCore.QRect(20, 420, 101, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        
        ### Flake image text label
        self.flake_image_label.setFont(font)
        self.flake_image_label.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))
        self.flake_image_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.flake_image_label.setFrameShadow(QtWidgets.QFrame.Plain)
        self.flake_image_label.setObjectName("flake_image_label")
        
        ### Move stage button 
        self.movestage_button = QtWidgets.QPushButton(self.centralwidget)
        self.movestage_button.setGeometry(QtCore.QRect(310, 415, 150, 32))
        self.movestage_button.setObjectName("movestage_button")
        self.movestage_button.clicked.connect(self.move_stage_to_flake_10x)

        ### Move stage button 50x
        self.movestage_button_50x = QtWidgets.QPushButton(self.centralwidget)
        self.movestage_button_50x.setGeometry(QtCore.QRect(500, 415, 150, 32))
        self.movestage_button_50x.setObjectName("movestage_button_50x")
        self.movestage_button_50x.clicked.connect(self.move_stage_to_flake_50x)
        
        ### Manual stage operation
        self.left_button = QtWidgets.QPushButton(self.centralwidget)
        self.left_button.setGeometry(QtCore.QRect(20, 290, 50, 40))
        self.left_button.setObjectName("left_button")
        self.left_button.clicked.connect(self.movestage_left)

        self.right_button = QtWidgets.QPushButton(self.centralwidget)
        self.right_button.setGeometry(QtCore.QRect(120, 290, 50, 40))
        self.right_button.setObjectName("left_button")
        self.right_button.clicked.connect(self.movestage_right)
        
        self.up_button = QtWidgets.QPushButton(self.centralwidget)
        self.up_button.setGeometry(QtCore.QRect(70, 252, 50, 40))
        self.up_button.setObjectName("left_button")
        self.up_button.clicked.connect(self.movestage_up)
        
        self.down_button = QtWidgets.QPushButton(self.centralwidget)
        self.down_button.setGeometry(QtCore.QRect(70, 328, 50, 40))
        self.down_button.setObjectName("left_button")
        self.down_button.clicked.connect(self.movestage_down)
        
        ### Slider Widget
        self.slider = QtWidgets.QSlider(self.centralwidget)
        self.slider.setGeometry(QtCore.QRect(270, 328, 100, 40))
        self.slider.setOrientation(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.change_multiplicator)
        self.slider_label = QtWidgets.QLabel(self.centralwidget)
        
        ### Label displaying Step-multiplicator
        self.multiplicator_label = QtWidgets.QLabel(self.centralwidget)
        self.multiplicator_label.setGeometry(QtCore.QRect(245, 326, 20, 40))

        ### Divider lines
        self.dividerline_1 = QtWidgets.QFrame(self.centralwidget)
        self.dividerline_1.setGeometry(QtCore.QRect(20, 400, 1141, 20))
        self.dividerline_1.setFrameShape(QtWidgets.QFrame.HLine)
        self.dividerline_1.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.dividerline_1.setObjectName("dividerline_1")
        self.dividerline_2 = QtWidgets.QFrame(self.centralwidget)
        self.dividerline_2.setGeometry(QtCore.QRect(820, 0, 20, 401))
        self.dividerline_2.setFrameShape(QtWidgets.QFrame.VLine)
        self.dividerline_2.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.dividerline_2.setObjectName("dividerline_2")
        self.frame = QtWidgets.QFrame(self.centralwidget)
        self.frame.setGeometry(QtCore.QRect(880, 10, 271, 281))
        self.frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frame.setObjectName("frame")
        
        ### Cropped flake image 
        self.cropped_flake_box = QtWidgets.QLabel(self.centralwidget)
        self.cropped_flake_box.setGeometry(QtCore.QRect(660, 450, 499, 391))
        self.cropped_flake_box.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.cropped_flake_box.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.cropped_flake_box.setLineWidth(4)
        self.cropped_flake_box.setText("")
        self.cropped_flake_box.setPixmap(QtGui.QPixmap("../17062022_12_11/flakes/zoomed_sb_flakes/mono_10x_flake_316.jpg"))
        self.cropped_flake_box.setScaledContents(True)
        self.cropped_flake_box.setIndent(-1)
        self.cropped_flake_box.setObjectName("cropped_flake_box")
        
        # Start scan button
        self.startscan_button = QtWidgets.QPushButton(self.centralwidget)
        self.startscan_button.setGeometry(QtCore.QRect(190, 20, 150, 32))
        self.startscan_button.setObjectName("startscan_button")
        self.startscan_button.clicked.connect(self.runGridscan)
        
        self.formLayoutWidget = QtWidgets.QWidget(self.centralwidget)
        self.formLayoutWidget.setGeometry(QtCore.QRect(60, 40, 211, 111))
        self.formLayoutWidget.setObjectName("formLayoutWidget")
        self.formLayout = QtWidgets.QFormLayout(self.formLayoutWidget)
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.formLayout.setObjectName("formLayout")
        self.label_10 = QtWidgets.QLabel(self.formLayoutWidget)
        self.label_10.setObjectName("label_10")
        self.formLayout.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.label_10)
        self.label_11 = QtWidgets.QLabel(self.formLayoutWidget)
        self.label_11.setObjectName("label_11")
        self.formLayout.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.label_11)
        self.label_12 = QtWidgets.QLabel(self.formLayoutWidget)
        self.label_12.setObjectName("label_12")
        self.formLayout.setWidget(2, QtWidgets.QFormLayout.LabelRole, self.label_12)
        
        # Message Output Box
        self.message_output_box = QtWidgets.QTextEdit(self.centralwidget)
        self.message_output_box.setGeometry(QtCore.QRect(480, 30, 320, 351))
        self.message_output_box.setObjectName("message_output_box")
        
        self.flake_image_label_2 = QtWidgets.QLabel(self.centralwidget)
        self.flake_image_label_2.setGeometry(QtCore.QRect(480, 0, 161, 31))
        font = QtGui.QFont()
        font.setFamily("Arial")
        font.setPointSize(12)
        self.flake_image_label_2.setFont(font)
        self.flake_image_label_2.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))
        self.flake_image_label_2.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.flake_image_label_2.setFrameShadow(QtWidgets.QFrame.Plain)
        self.flake_image_label_2.setObjectName("flake_image_label_2")

        self.widget = QtWidgets.QWidget(self.centralwidget)
        self.widget.setGeometry(QtCore.QRect(880, 320, 271, 56))
        self.widget.setObjectName("widget")
        self.gridLayout = QtWidgets.QGridLayout(self.widget)
        self.gridLayout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setVerticalSpacing(0)
        self.gridLayout.setObjectName("gridLayout")
        
        ### Time remaining label
        self.t_remain_label = QtWidgets.QLabel(self.widget)
        self.t_remain_label.setEnabled(True)
        font = QtGui.QFont()
        font.setFamily("Arial")
        font.setPointSize(13)
        self.t_remain_label.setFont(font)
        self.t_remain_label.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))
        self.t_remain_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.t_remain_label.setFrameShadow(QtWidgets.QFrame.Plain)
        self.t_remain_label.setLineWidth(1)
        self.t_remain_label.setAlignment(QtCore.Qt.AlignCenter)
        self.t_remain_label.setIndent(0)
        self.t_remain_label.setObjectName("t_remain_label")
        self.gridLayout.addWidget(self.t_remain_label, 0, 0, 1, 1)
        
        ### Progress Bar
        self.progressBar = QtWidgets.QProgressBar(self.widget)
        self.progressBar.setProperty("value", 24)
        self.progressBar.setObjectName("progressBar")
        self.progressBar.setValue(0)
        self.gridLayout.addWidget(self.progressBar, 1, 0, 1, 1)
        
        # Home Stage Button
        self.start_homing_button = QtWidgets.QPushButton(self.centralwidget)
        self.start_homing_button.setGeometry(QtCore.QRect(20, 20, 150, 32))
        self.start_homing_button.setObjectName("start_homing_button")
        self.start_homing_button.clicked.connect(self.runHoming)
        
        # Constants 
        self.step_multiplicator = 10
        
        # Menubar
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1175, 37))
        self.menubar.setObjectName("menubar")
        self.menuFile = QtWidgets.QMenu(self.menubar)
        self.menuFile.setGeometry(QtCore.QRect(347, 120, 119, 62))
        self.menuFile.setObjectName("menuFile")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.actionOpen = QtWidgets.QAction(MainWindow)
        self.actionOpen.setObjectName("actionOpen")
        self.menuFile.addAction(self.actionOpen)
        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.setNativeMenuBar(False)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "MainWindow"))
        __sortingEnabled = self.flake_list.isSortingEnabled()
        self.flake_list.setSortingEnabled(False)
        self.flake_list.setSortingEnabled(__sortingEnabled)
        self.flake_image_label.setText(_translate("MainWindow", "Flake Image:"))
        self.movestage_button.setText(_translate("MainWindow", "Move Stage to Flake 10x"))
        self.movestage_button_50x.setText(_translate('MainWindow', 'Move Stage to Flake 50x'))
        self.startscan_button.setText(_translate("MainWindow", "Start Scan"))
        self.left_button.setText(_translate('MainWindow', 'Left'))
        self.right_button.setText(_translate('MainWindow', 'Right'))
        self.up_button.setText(_translate('MainWindow', 'Up'))
        self.down_button.setText(_translate('MainWindow', 'Down'))
        self.flake_image_label_2.setText(_translate("MainWindow", "Output Messages:"))
        self.start_homing_button.setText(_translate("MainWindow", "Home Stage"))
        self.t_remain_label.setText(_translate("MainWindow", ""))
        # self.label_3.setText(_translate("MainWindow", "homing stage..."))
        self.menuFile.setTitle(_translate("MainWindow", "File"))
        self.actionOpen.setText(_translate("MainWindow", "Open..."))
        self.actionOpen.setShortcut(_translate("MainWindow", "Ctrl+O"))
        self.actionOpen.triggered.connect(self.load_previous_scan)


    def setProgressVal(self, val):
        '''Sets the value of the progress bar to a new value'''
        self.progressBar.setValue(val)
      
    def movestage_left(self):
        '''Moves the stage one step to the left.'''
        stage_x = Thorlabs.KinesisMotor('27261810')
        stage_x.move_by(-10*self.step_multiplicator)
        stage_x.wait_move()
        stage_x.close()
        
    def movestage_right(self):
        '''Moves the stage one step to the right.'''
        stage_x = Thorlabs.KinesisMotor('27261810')
        stage_x.move_by(10*self.step_multiplicator)
        stage_x.wait_move()
        stage_x.close()        
        
    def movestage_up(self):
        '''Moves the stage one step upwards.'''
        stage_y = Thorlabs.KinesisMotor('27261747')
        stage_y.move_by(10*self.step_multiplicator)
        stage_y.wait_move()
        stage_y.close()        
         
    def movestage_down(self):
        '''Moves the stage one step downwards.'''
        stage_y = Thorlabs.KinesisMotor('27261747')
        stage_y.move_by(-10*self.step_multiplicator)
        stage_y.wait_move()
        stage_y.close()        
        
    def change_multiplicator(self, value):
        '''Increases the step_multiplicator non-linearly depending on the slider position.
        '''
        self.multiplicator_label.setText((str(value)))
        self.step_multiplicator = value**1.8
                
    def move_stage_to_flake_10x(self):
        '''Moves the stage to the location of the flake and centers it on the image frame. Image data is read in from a .csv-file containing all the information.
        '''
        conversion_umstep = 300/8.6818
        conversion_pxum = 520/1280
        conversion_pxstep = conversion_pxum * conversion_umstep
        center_dis_x = 8500
        center_dis_y = 7300
        
        df_imagedata = pd.read_csv(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/image_data.csv')
        df_flakes = df_imagedata.loc[df_imagedata.flake_tag == True].sort_values('score', ascending=False)

        df_flakes['flake_loc_x_step'] = df_flakes['x_pos'] - 1*df_flakes['flake_loc_x'] * conversion_pxstep + 1*center_dis_x
        df_flakes['flake_loc_y_step'] = df_flakes['y_pos'] + 1*df_flakes['flake_loc_y'] * conversion_pxstep - 1*center_dis_y
        dict_flakes = df_flakes.to_dict('index')

        # time.sleep(3)
        self.updateMessagebox(f'Moved stage to Flake {self.image_number}')
        stage_x = Thorlabs.KinesisMotor('27261810')
        stage_y = Thorlabs.KinesisMotor('27261747')
        stage_x.move_to(dict_flakes[int(self.image_number)]['flake_loc_x_step'])
        stage_y.move_to(dict_flakes[int(self.image_number)]['flake_loc_y_step'])
        stage_y.wait_move()
        stage_x.close()
        stage_y.close()
        
    def move_stage_to_flake_50x(self):
        '''Moves the stage to the location of the flake and centers it on the image frame for the 50x objective lense. Image data is read in from a .csv-file containing all the information.
        '''
        conversion_umstep = 300/8.6818
        self.updateMessagebox(f'Moved stage to Flake {self.image_number} (50x-shifted)')
        stage_x = Thorlabs.KinesisMotor('27261810')
        stage_y = Thorlabs.KinesisMotor('27261747')
        stage_x.move_by(-1036)
        stage_y.move_by(+4319)
        stage_y.wait_move()
        stage_x.close()
        stage_y.close()
        
    def runHoming(self):
        '''Calling the HomingThread in order to home the stage in a separate thread.
        '''
        # Step 2: Create a QThread object
        self.thread = QThread()
        # Step 3: Create a worker object
        self.workerhoming = HomingThread()
        # Step 4: Move worker to the thread
        self.workerhoming.moveToThread(self.thread)
        # Step 5: Connect signals and slots
        self.thread.started.connect(self.workerhoming.run)
        self.workerhoming.statusUpdate.connect(self.updateMessagebox)
        # self.workergridscan.change_value.connect(self.setProgressVal)
        self.workerhoming.finished.connect(self.thread.quit)
        self.workerhoming.finished.connect(self.workerhoming.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        # Step 6: Start the thread
        self.thread.start()
        
    def updateRemainingtime(self, remainingtime):
        '''The remaining scan time is updated after storing an image and the corresponding label is updated.
        '''
        rs = remainingtime.total_seconds()  # remaining time in seconds (rs)
        self.t_remain_label.setText('{}m {}s remaining..'.format(int(rs % 3600 // 60), int(rs % 60)))

    def updateMessagebox(self, message):
        '''The function takes the message sent as a signal and prints the message to the output box in the GUI.
        '''
        self.message_output_box.append(datetime.now().strftime('[%H:%M:%S]') 
                                        + '\t' + message)

    def runGridscan(self):
        '''The separate grid scan thread is called and its signals are defined. '''
        ### Step 1: Create a QThread object
        self.thread = QThread()
        ### Step 2: Create a worker object
        self.workergridscan = GridscanThread()
        ### Step 3: Move worker to the thread
        self.workergridscan.moveToThread(self.thread)
        # Step 4: Connect signals and slots
        self.thread.started.connect(self.workergridscan.run)
        self.workergridscan.refresh_flakelist.connect(self.flakeslist_livescan)
        self.workergridscan.statusUpdate.connect(self.updateMessagebox)
        self.workergridscan.timeUpdate.connect(self.updateRemainingtime)
        self.workergridscan.change_value.connect(self.setProgressVal)
        self.workergridscan.flush_listwidget.connect(self.flush_listwidget)
        self.workergridscan.finished.connect(self.thread.quit)
        self.workergridscan.finished.connect(self.workergridscan.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        # Step 5: Start the thread
        self.thread.start()
    
        
    def textEditBox(self):
        '''Status message box is initiated in a separate thread in order to update it during the execution of a grid scan.'''
        self.thread = StatusMessage_Thread()
        self.thread.change_value.connect(self.printStatusMessage)
        self.thread.start()
        
        
    def printStatusMessage(self, val):
        ''''''
        self.message_output_box.append(datetime.now().strftime('[%H:%M:%S]') + '\t' + 'Homing in process...')


    def changeImage(self, image_number):
        '''Displayed flake images (uncropped and cropped) are changed.'''
        print(self.dir)
        self.uncropped_flake_box.setPixmap(QtGui.QPixmap(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/flakes/uncropped/mono_10x_{image_number}.jpg'))
        self.cropped_flake_box.setPixmap(QtGui.QPixmap(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/flakes/highlighted/bi_10x_{image_number}.jpg'))        
        
    def selectionChanged(self):
        '''Whenever the selection on the flake list is changed, this function is called and the image number is updated. Then the changeImage function is called with the new image number.
        '''
        self.image_number = self.flake_list.selectedItems()[0].text()
        self.changeImage(str(self.image_number))

    def load_previous_scan(self):
        '''By clicking the file dialog "select directory" a new grid scan directory is selected and the corresponding lists, labels and images are updated in the GUI.
        '''
        self.dir = str(QFileDialog.getExistingDirectory(None, "Select Directory"))
        self.dir = self.dir.rsplit('/',1)[1]
        # path = pathlib.PurePath(self.dir)
        # print(path)
        # print(os.path.normpath(self.dir))
        
        self.df_image_data = pd.read_csv(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/image_data.csv')
        
        img_count = self.df_image_data.loc[self.df_image_data.flake_tag == True].img_count.to_list()
        img_count = [str(s) for s in img_count]
        # img_count = ['Image_' + str(s) for s in img_count]
        self.flake_list.clear()
        self.flake_list.addItems(img_count)
        self.updateMessagebox(f"Data loaded from {self.dir}")

    def flush_listwidget(self):
        '''The flake list widget is flushed during the import of a new grid scan data set.
        '''
        self.flake_list.clear()
        print('FLUSH flake_list')
        
    def flakeslist_livescan(self, dir):
        '''Gets the current scan directory as input variable and reads the .csv-file from it. Then the image read csv-data is extracted and added to the flakes list widget.
        '''
        self.dir = dir
        print(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/image_data.csv')
        self.df_image_data = pd.read_csv(f'./Grid_Scans_WSe2BilayerScript/{self.dir}/image_data.csv')
        img_count = self.df_image_data.loc[self.df_image_data.flake_tag == True].img_count.to_list()
        img_count = [str(s) for s in img_count]
        self.flake_list.addItem(img_count[-1])
        return img_count

    
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = QtWidgets.QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    sys.exit(app.exec_())


