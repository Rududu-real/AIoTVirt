# install imutils
sudo pip install imutils
sudo pip3 install opencv-python
sudo easy_install python-prctl
# then... we don't need the previous installation???

# this is due to a change in imutils codes for camera thread naming. 
sudo su
cd ../surveillance/misc
cp pivideostream.py /usr/local/lib/python3.5/site-packages/imutils/video
cp videostream.py /usr/local/lib/python3.5/site-packages/imutils/video
exit
