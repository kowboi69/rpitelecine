#!/usr/bin/env python
#
# RPi Telecine - Set up the telecine job
#
# Commandline/interactive opencv program to setup the telecine
# job. Command line arguments allow setting of job name, brackets
# film type.
# Then an opencv window opens to allow tuning of the exposure crop, etc.
# Using the opencv window does require an X server - it will
# work, albeit very slowly, over an ssh connection
#
# Copyright (c) 2015, Jason Lane
# 
# Redistribution and use in source and binary forms, with or without modification, 
# are permitted provided that the following conditions are met:
# 
# 1. Redistributions of source code must retain the above copyright notice, this 
# list of conditions and the following disclaimer.
# 
# 2. Redistributions in binary form must reproduce the above copyright notice, 
# this list of conditions and the following disclaimer in the documentation and/or 
# other materials provided with the distribution.
# 
# 3. Neither the name of the copyright holder nor the names of its contributors 
# may be used to endorse or promote products derived from this software without 
# specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED 
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR 
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES 
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; 
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON 
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT 
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS 
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import division

import argparse
import cv2

from tc_common import *

help_text = """Keys:
s	Save current settings
Esc	Escape without saving
c	Toggle clipped colours
g	Toggle grayscale
d	Cycle through DRC settings (off,low,med,high)
-|+	Reduce|increase shutter
r | R	Reduce|increase red gain
b | B	Reduce|increase blue gain
p	Toggle perforation detection
o	Centre frame
i	Redetect perforation
#	Calibrate Transport (same as u/t/y)
t | y	Calibrate transport forward/backward
u	Calibrate pixels per motor step
. | ,	Previous|next frame
< | >	Back|forwards 18 frames
[ | ]	Fast wind back | forward 18 frames
{ | }	Fast wind back | forward 180 frames
Arrows	Move crop
PgUp	Make crop larger
PgDn	Make crop smaller
Home	Nudge motor forward
End	Nudge motor backward
1-4	Display reduction (1 full size, 4 quarter size)"""

scale_display = 3

saving = False

def get_pixels_per_step(times=5):
    # Establishes how many pixels in the image per motor step
    # Takes an average
    steps = 60
    counts = []
    tc.tension_film()
    for n in range(times):
	centre_frame()
	img = cam.take_picture()
	pf.find(img)
	centre = pf.centre[1]
	tc.steps_forward(steps)
	img = cam.take_picture()
	pf.find(img)
	found1 = pf.found
	if found1:
	    pixels_per_step = abs(pf.yDiff)/float(steps)
	    counts.append(pixels_per_step)
	    centre = pf.centre[1]
	tc.steps_back(steps*2)
	img = cam.take_picture()
	pf.find(img)
	found2 = pf.found
	if found2:
	    pixels_per_step = (pf.yDiff)/float(steps*2)
	    counts.append(pixels_per_step)
	tc.steps_forward(steps)
	if not(found1 and found2):
	    # Perforation went out of view - so reduce number of steps
	    steps = int(steps/1.4)
    cnf.pixels_per_step = sum(counts)/len(counts)
    print("Pixels per step:{}".format(cnf.pixels_per_step))

def calibrate_transport(frames=18,d=True):
    # Calibrate the film transport over a number of frames
    # This establishes how many motor steps are needed on average
    # for a sequence of frames. d=True - move forwards, else move backwards
    steps_per_frame = []
    ave_steps = cnf.ave_steps_fd if d else cnf.ave_steps_bk
    pixels_per_step = max(2,min(10,cnf.pixels_per_step))
    #tc.tension_film()
    print('Calibrating ' + 'Forward' if d else 'Backward')
    print('Pixels per step:{:.3f}'.format(pixels_per_step))
    centre_frame()
    steps = 250 # Jump a minimum number of steps
    for n in range(frames):
	print('Calibrating - frame:%d'%(n))
	diff=500
	tc.steps_forward(steps) if d else tc.steps_back(steps)
	while abs(diff)>10:
	    # Zero in on centre point 
	    img = cam.take_picture()
	    pf.find(img)
	    if pf.found:
		diff = pf.yDiff
		s = int(round(abs(diff)/pixels_per_step))
		if s<2: s=2
		print('Diff: {} s: {}'.format(diff,s))
		if diff < -10:
		    tc.steps_back(s)
		    steps = steps-s if d else steps+s
		elif diff > 10:
		    tc.steps_forward(s)
		    steps = steps+s if d else steps-s
		else:
		    # Pretty close to the centre
		    steps_per_frame.append(steps) 
		    #print('Steps %d'%(steps))
	    else:
		# Need to put something a bit more intelligent here 
		# when we fail to read a perforation
		print "perforation not found"
		tc.steps_forward(20) if d else tc.steps_back(20)
		steps += 20
    ave_steps = int(round(sum(steps_per_frame)/float(len(steps_per_frame))))
    print('Steps per frame:')
    print(steps_per_frame)
    print('Ave steps over %d frames is %d'%(len(steps_per_frame),ave_steps))
    print('Min:%d Max:%d'%(min(steps_per_frame),max(steps_per_frame)))
    if d:
	cnf.ave_steps_fd = ave_steps
    else:
	cnf.ave_steps_bk = ave_steps

def draw_perforation(img):
    # Draw the perforation on the image
    # Calculate various metrics of the perforation
    x, y = pf.position
    w, h = pf.expectedSize
    r, b = ( x+w , y+h )	# Right and bottom
    cnf.perf_size = (w,h)
    cnf.perf_cx = pf.centre[0]
    # Draw perforation on preview
    print pf.centre
    cv2.rectangle(img,(x,y),(r,b),(0,0,255),5)
    cv2.circle(img,pf.centre,5,(255,0,255),4) # Centre of perforation
    cv2.line(img,pf.centre,(pf.centre[0],pf.ROIcentrexy[1]),(255,0,0),4)
    # Crop
    if cnf.crop_size == [0,0]:
	# Calculate crop size from size of perforation
	cnf.crop_size[1] = int(round(h*pf.frameHeightMultiplier[cnf.film_type]*1.1))
	cnf.crop_size[0] = int(round(cnf.crop_size[1] * 1.3333))
	cnf.crop_offset[0] = cnf.perf_size[0]//4
	if cnf.film_type == 'super8':
	    cnf.crop_offset[1] = -(cnf.crop_size[1]//2)
	else: # std8
	    cnf.crop_offset[1] = -(cnf.perf_size[1]//8)
    cnf.crop_x = pf.centre[0]+cnf.crop_offset[0]
    cnf.crop_y = pf.centre[1]+cnf.crop_offset[1]
    cv2.rectangle(img,(cnf.crop_x,cnf.crop_y),\
	    (cnf.crop_x+cnf.crop_size[0], cnf.crop_y+cnf.crop_size[1]),\
		(0,255,0),4)

def draw_roi(img):
    # Draws a rectangle showing the ROI area
    if pf.isInitialised:
	cv2.rectangle(img,(pf.ROIslice[1].start,pf.ROIslice[0].start),\
			    (pf.ROIslice[1].stop,pf.ROIslice[0].stop),(0,255,255),3)

def play_frames(frames=18,dr=True):
    # Move forward/back by a number of frames, displaying each one
    global scale_display
    for n in range(frames):
	next_frame() if dr else prev_frame()
	img = cam.take_picture()
	pf.find(img)
	caption = '{}: {}'.format('Forward' if dr else 'Backward',n)
	if cnf.show_gray:
	    img = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
	display_image('Telecine',img,reduction=scale_display,text=caption)
	k = 0xFFFF & cv2.waitKey(1)
	if k==cv2_keys['Escape']:
	    break
	    
def adjust_crop(key,img_w,img_h):
    # Move, resize crop
    steps = 10
    if(key==cv2_keys['LeftArrow']):
	print('Crop left')
	if (pf.centre[0]+cnf.crop_offset[0])>steps:
	    cnf.crop_offset[0] -= steps
    elif (key==cv2_keys['RightArrow']):
	print('Crop right')
	if (pf.centre[0]+cnf.crop_offset[0]+cnf.crop_size[0])+steps < img_w:
	    cnf.crop_offset[0] += steps
    elif (key==cv2_keys['UpArrow']):
	print('Crop up')
	if (pf.centre[1]+cnf.crop_offset[1])>steps:
	    cnf.crop_offset[1] -= steps
    elif (key==cv2_keys['DownArrow']):
	print('Crop down')
	if (pf.centre[1]+cnf.crop_offset[1]+cnf.crop_size[1])+steps < img_h:
	    cnf.crop_offset[1] += steps
    elif (key==cv2_keys['PgDn']):
	print('Crop smaller')
	if cnf.crop_size[1] > steps:
	    cnf.crop_size[1] -= steps
	    cnf.crop_size[0] = int(round(cnf.crop_size[1] * 1.3333))
    elif (key==cv2_keys['PgUp']):
	print('Crop larger')
	if (pf.centre[1]+cnf.crop_offset[1]+cnf.crop_size[1])+steps < img_h:
	    cnf.crop_size[1] += steps
	    cnf.crop_size[0] = int(round(cnf.crop_size[1] * 1.3333))


def setup_telecine():
    global saving, scale_display
    # Set up perforation finding, cropping
    # Now do the visual setup.
    try:
	
	def mouse_handler(event,x,y,flags,param):
	    # mouse callback function
	    if event == cv2.EVENT_LBUTTONDOWN:
		x = x * scale_display
		y = y * scale_display
		img = cam.take_picture()
		pf.findFirstFromCoords(img,(x,y),20)
		if pf.found:
		    x,y = pf.position
		    w,h = pf.expectedSize
		    pf.found = pf.find(img)
		    draw_perforation(img)
		    caption = "Perforation found: {} {}".format(pf.position,pf.expectedSize)
		    print caption
		    display_image('Telecine',img,reduction=scale_display,text=caption)
		
	cv2.namedWindow('Telecine')
	cv2.setMouseCallback('Telecine',mouse_handler)

	tc.light_on()
	cam.setup_cam(cnf.awb_gains, cnf.shutter_speed)
	capturing = True
	show_clipped = False
	show_perf = True
	col_clip = 0
	while capturing:
	    cam.shutter_speed = cnf.shutter_speed
	    cam.awb_gains = cnf.awb_gains
	    cam.drc_strength = cnf.drc  # Will work after picamera 1.6
	    cam.image_effect = cnf.image_effect
	    img = cam.take_picture()
	    img_h,img_w = img.shape[:2]
	    caption = ( "Shutter speed: {} gain_r:{:.3f} gain_b:{:.3f}".\
		    format(cam.shutter_speed,cnf.awb_gains[0],cnf.awb_gains[1]) )
	    if show_perf and pf.isInitialised:
		    # Find perforation
		    pf.find(img)
		    if pf.found:
			print('Perforation found: {} {}'.format(pf.position,pf.expectedSize))
		    else:
			print('Perforation not found.')
	    if cnf.show_gray:
		# Convert to gray and then back to colour so we can display crop in colour
		gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
		img = cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
	    if show_clipped:
		ret,img = cv2.threshold(img,254,255,cv2.THRESH_BINARY)
	    if show_perf and pf.found:
		# Display perforation
		draw_perforation(img)
		caption = caption +' crop: %d:%d %dx%d'%(cnf.crop_offset[0],cnf.crop_offset[1],cnf.crop_size[0],cnf.crop_size[1])
	    draw_roi(img)
	    # Disply image and wait for user input	
	    display_image('Telecine',img,reduction=scale_display,text=caption)
	    key = 0xFFFF & cv2.waitKey(0) 
	    if key==cv2_keys['Escape']:
		capturing = False
		saving = False
	    elif key==ord('s'):
		capturing = False
		saving = True
	    elif key==cv2_keys['Home']:
		print("Nudge forward")
		tc.steps_forward(20)
	    elif key==cv2_keys['End']:
		print("Nudge backward")
		tc.steps_back(20)
	    elif key==ord('o'):
		print('Centering frame')
		centre_frame()
	    elif key==ord('#'):
		print('Calibrating transport')
		print('Discovering pixels per motor step')
		get_pixels_per_step()
		print('Calibrating steps per frame forwards')
		calibrate_transport(24,True)
		print('Calibrating steps per frame backwards')
		calibrate_transport(24,False)
	    elif key==ord('t'):
		print('Calibrating steps per frame forwards')
		calibrate_transport(24,True)
	    elif key==ord('y'):
		print('Calibrating steps per frame backwards')
		calibrate_transport(24,False)
	    elif key==ord('u'):
		print('Discovering pixels per motor step')
		get_pixels_per_step()
	    elif key==ord('w'):
		print('Tensioning film')
		tc.tension_film()
	    elif key==ord('.'):
		print('Next frame')
		next_frame()
	    elif key==ord('>'):
		print('Play 18 frames forwards')
		play_frames(18,True)
	    elif key==ord(','):
		print('Previous frame')
		prev_frame()
	    elif key==ord('<'):
		print('Play 18 frames backwards')
		play_frames(18,False)
	    elif key==ord(']'):
		print('Wind forward 18 frames')
		fast_wind(18,True)
	    elif key==ord('['):
		print('Wind backward 18 frames')
		fast_wind(18,False)
	    elif key==ord('}'):
		print('Wind forward 180 frames')
		fast_wind(180,True)
	    elif key==ord('{'):
		print('Wind backward 180 frames')
		fast_wind(180,False)	    
	    elif key==ord('+') or key==ord('=') and cnf.shutter_speed < 30000:
		print('Increase shutter time')
		cnf.shutter_speed += int(cnf.shutter_speed*0.05)
	    elif key==ord('-') or key==ord('_') and cnf.shutter_speed > 100:
		print('Decrease shutter time')
		cnf.shutter_speed -= int(cnf.shutter_speed*0.05)
	    elif key==ord('c'):
		print('Toggle clipped pixels')
		show_clipped = not show_clipped
	    elif key==ord('1'):
		print('Full size preview')
		scale_display = 1
	    elif key==ord('2'):
		print('Half size preview')
		scale_display = 2
	    elif key==ord('3'):
		print('Third size preview')
		scale_display = 3
	    elif key==ord('4'):
		print('Quarter size preview')
		scale_display = 4
	    elif key==ord('p'):
		print('Toggle perforation display')
		show_perf = not show_perf
	    elif key==ord('g'):
		print('Toggle grayscale display')
		cnf.show_gray = not cnf.show_gray
	    elif key==ord('r') and cnf.awb_gains[0] > 0.3:
		print('Decrease red gain')
		cnf.awb_gains[0] -= cnf.awb_gains[0]*0.05
	    elif key==ord('R') and cnf.awb_gains[0] < 5:
		print('Increase red gain')
		cnf.awb_gains[0] += cnf.awb_gains[0]*0.05
	    elif key==ord('b') and cnf.awb_gains[0] > 0.3:
		print('Decrease blue gain')
		cnf.awb_gains[1] -= cnf.awb_gains[1]*0.05
	    elif key==ord('B') and cnf.awb_gains[0] < 5:
		print('Increase blue gain')
		cnf.awb_gains[1] += cnf.awb_gains[1]*0.05
	    elif key==ord('d'):
		# Toggle through DRC setting
		i = cnf.drc_values.index(cnf.drc)
		i = (i+1) % len(cnf.drc_values)
		cnf.drc = cnf.drc_values[i]
		print('DRC: {}'.format(cnf.drc))
	    elif key==ord('e'):
		# Toggle through image effects
		i = cnf.image_effect_values.index(cnf.image_effect)
		i = (i+1) % len(cnf.image_effect_values)
		cnf.image_effect = cnf.image_effect_values[i]
		print('Image Effect: {}'.format(cnf.image_effect))
	    elif key==ord('E'):
		print('Reset Image Effect')
		cnf.image_effect = cnf.image_effect_values[0]
	    elif show_perf and pf.found:
		# Allow adjustment of crop
		adjust_crop(key,img_w,img_h)
    finally:
	tc.light_off()
	cam.close()
	cv2.destroyAllWindows

if __name__ == '__main__':
    # Command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('jobname', help='Name of the telecine job')
    parser.add_argument('-s8','--standard8', help='Using Standard 8 film', action='store_true')
    parser.add_argument('-b','--brackets', help='Bracket exposures', action='store_true')
    args = parser.parse_args()

    job_name = sanitise_job_name(args.jobname)
    
    print('Job name: '+ job_name)
    
    # Config file
    # Read job config file - so we retain existing settings
    cnf.read_configfile(job_name)

    if args.standard8:
	print('Standard 8 film chosen')
	cnf.film_type = 'std8'
    else:
	print('Super 8 film chosen')
	cnf.film_type = 'super8'
    if cnf.perf_size:
        pf.init( filmType=cnf.film_type, imageSize=cam.MAX_IMAGE_RESOLUTION,
                    expectedSize=cnf.perf_size, cx=cnf.perf_cx )
    else:
        pf.setFilmType(cnf.film_type)

    if args.brackets:
	print('Bracketing on')
    cnf.brackets = args.brackets

    print(help_text)

    setup_telecine()

    if saving:
	print('Writing config file: %s'%(cnf.configname))
	cnf.write_configfile()

    print('Bye...')
