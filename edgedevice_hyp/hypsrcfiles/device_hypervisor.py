import argparse
import configparser
import sys
import time
from datetime import datetime,date
sys.path.insert(0, '../../messaging')
from message_bus import MessageBus
from utils import visualize_output
from utils import deserialize_output
import mvnc.mvncapi as mvnc
import dlib
import json
import redis
import cv2
import numpy as np
import psutil
import ast
import threading
import imutils
from imutils.object_detection import non_max_suppression
import signal
import ntplib
import trackableobject 
import centroidtracker


#
# Reads a graph file into a buffer
#
def load_graph(graph_file, device):
    with open(graph_file, mode='rb') as f:
        blob = f.read()

    # Load the graph buffer into the NCS
    graph = device.AllocateGraph(blob)
    return graph

#
# Decorator for threading methods in a class
#
def threaded(fn):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread
    return wrapper


class Hypervisor(object):
    def __init__(self, name, port, ip_ext, port_ext, ifname, controller_ip, controller_port, live, tr_method):
        self.device_name = name
        self.device_port = port
        self.device_ip_ext = ip_ext
        self.device_port_ext = port_ext
        self.ifname = ifname
        self.controller_ip = controller_ip
        self.controller_port = controller_port

        self.msg_bus = MessageBus(name, port, 'camera')
        self.msg_bus.register_callback('device_list', self.handle_message)
        self.msg_bus.register_callback('migration_request', self.handle_message)
        signal.signal(signal.SIGINT, self.signal_handler)


        self.camera = None  # OpenCV camera object
        self.live = live
        self.tr_method = tr_method
        self.labels = None
        self.confidence_threshold = 0.80
        self.redis_db = None
        self.display = 'off'
        self.graph_file = ''
        self.width = 600
        self.height = 400
        self.counter = 0
        self.color_mode = 'bgr'
        self.dimensions = [224, 224]
        self.mean = [127.5, 127.5, 127.5]
        self.scale = 0.00789
        self.starttime = time.time()
        self.logfile = None
#        self.timegap = datetime.datetime()
        self.gettimegap()
        self.frame_skips = 10
        self.ct = None
        self.trackers = []
        self.trackableObjects = {}

    def gettimegap(self):
        starttime = datetime.now()
        ntp_response = ntplib.NTPClient().request('2.kr.pool.ntp.org', version=3)
        returntime = datetime.now()
        self.timegap = datetime.fromtimestamp(ntp_response.tx_time) - starttime - (returntime - starttime)/2

    def cpuusage(self):
        return psutil.cpu_percent()

    def ramusage(self):
        return psutil.virtual_memory()

    def signal_handler(self, sig, frame):
        self.logfile.close()
        print('closing logfile, exiting')
        sys.exit(0)

    def load_labels(self, labels_file):
        self.labels = [ line.rstrip('\n') for line in
              open(labels_file) if line != 'classes\n']

    def handle_message(self, msg_dict):
        print('[Hypervisor] handle_message: %s' % msg_dict['type'])
        if msg_dict['type'] == 'device_list':
            # print(msg_dict)
            device_list = json.loads(msg_dict['devices'])
            for item in device_list:
                if item['device_name'] == self.device_name:
                    continue
                else:
                    print(' - adding a new node_info: ', item['device_name'])
                    self.msg_bus.node_table.add_entry(item['device_name'], item['ip'], item['port'], item['location'], item['capability'])

        elif msg_dict['type'] == 'migration_request':
            print(' - migration request')

        else:
            # Silently ignore invalid message types.
            pass

    def join(self):
        # Create a join message based on NIC information.
        # my_node_info = self.msg_bus.get_my_node_info(self.ifname)
        # print('My node info:', my_node_info)
        join_msg = dict(type='join', device_name=device_name, ip=self.device_ip_ext, port=self.device_port_ext,
                        location='N1_823_1', capability='no')
        self.msg_bus.send_message_json(self.controller_ip, self.controller_port, join_msg)

    def connect_redis_db(self, redis_port):
        self.redis_db = redis.Redis(host='localhost', port=redis_port, db=0)

    def open_ncs_device(self):
        # Look for enumerated NCS device(s); quit program if none found.
        devices = mvnc.EnumerateDevices()
        if len(devices) == 0:
            print("No devices found")
            quit()
        # Get a handle to the first enumerated device and open it
        device = mvnc.Device(devices[0])
        device.OpenDevice()
        return device

    def getfps(self, oldtime):
        curr_time = time.time()
        sec = curr_time - oldtime
        fps = 1 / sec
        return curr_time, fps
        


    def close_ncs_device(self, device, graph):
        graph.DeallocateGraph()
        device.CloseDevice()
        self.camera.release()
        cv2.destroyAllWindows()

    def pre_process_image(self, frame):
        # Resize image [Image size is defined by chosen network, during training]
        img = cv2.resize(frame, tuple(self.dimensions))

        # Convert RGB to BGR [OpenCV reads image in BGR, some networks may need RGB]
        if (self.color_mode == "rgb"):
            img = img[:, :, ::-1]

        # Mean subtraction & scaling [A common technique used to center the data]
        img = img.astype(np.float16)
        img = (img - np.float16(self.mean)) * self.scale

        return img

    #cascade here..
    def infer_image_haar(frame, fps):
        a = []
        curTime = time.time()
        body_cascade = cv2.CascadeClassifier('cascades/haarcascade_upperbody.xml')
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
        body = body_cascade.detectMultiScale(gray, 1.1, 8)
        infTime = time.time()-curTime 

        a = [[] for _ in range(len(pick))]
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()

        for i in len(body):

            for(xA, yA, xB, yB) in pick:
                a[i].append("90")
                a[i].append("15:person")
                (y1, x1) = (yA, xA)
                a[i].append(y1,x1)
                (y2, x2) = (yB, xB)
                a[i].append(y2,x2)

        save = {"elapsedtime": "{0:.2f}".format(elapsedtime), "CPU": str(cpu), "inftime": str("{0:.2f}".format(inftime)), "fps": str("{0:.2f}".format(fps)), "numberofobjects": str(len(pick)),"a": str(a)}
        r.hmset(counter, save)
        del(a)



    # hog codes here
    def infer_image_hog (frame, fps):
        a = []  
        
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        curTime = time.time()
        (rects, weights) = hog.detectMultiScale(frame, winStride=(4,4), padding=(8,8), scale=1.05)
        rects = np.array([[x,y,x+w,y+h] for (x,y,w,h) in rects])
        pick = non_max_suppression(rects, probs=None, overlapThresh=0.65)
        infTime = time.time()-curTime 
       
        a = [[] for _ in range(len(pick))]
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        for i in len(pick):
    
            for(xA, yA, xB, yB) in pick:
                a[i].append("90")
                a[i].append("15:person")
                (y1, x1) = (yA, xA)
                a[i].append(y1,x1)
                (y2, x2) = (yB, xB)
                a[i].append(y2,x2)

        self.counter += 1

        save = {"elapsedtime": "{0:.2f }".format(elapsedtime), "CPU": str(cpu), "inftime": str("{0:.2f}".format(inftime)), "fps": str("{0:.2f}".format(fps)), "numberofobjects": str(len(pick)),"a": str(a)}
        r.hmset(counter, save)
        del(a)

    def infer_image_fps(self, graph,img, frame, fps):
        # Load the image as a half-precision floating point array
        graph.LoadTensor(img, 'user object')

        # Get the results from NCS
        output, userobj = graph.GetResult()

        # Get execution time
        inference_time = graph.GetGraphOption(mvnc.GraphOption.TIME_TAKEN)

        # Deserialize the output into a python dictionary
        output_dict = deserialize_output.ssd(
            output,
            self.confidence_threshold,
            frame.shape)

        # print( "I found these objects in ( %.2f ms ):" % ( numpy.sum( inference_time ) ) )
        inftime = np.sum(inference_time)
        numobj = (output_dict['num_detections'])

        # create array for detected obj
        a = [[] for _ in range(numobj)]

        # print (numobj)
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()

        for i in range(0, output_dict['num_detections']):
            print("%3.1f%%\t" % output_dict['detection_scores_' + str(i)]
                  + self.labels[int(output_dict['detection_classes_' + str(i)])]
                  + ": Top Left: " + str(output_dict['detection_boxes_' + str(i)][0])
                  + " Bottom Right: " + str(output_dict['detection_boxes_' + str(i)][1]))
            #        print(str(i))
            a[i].append(output_dict['detection_scores_' + str(i)])
            a[i].append(self.labels[int(output_dict['detection_classes_' + str(i)])])
            a[i].append(str(output_dict['detection_boxes_' + str(i)][0]))
            a[i].append(str(output_dict['detection_boxes_' + str(i)][1]))
            # Draw bounding boxes around valid detections
            (y1, x1) = output_dict.get('detection_boxes_' + str(i))[0]
            (y2, x2) = output_dict.get('detection_boxes_' + str(i))[1]

            # Prep string to overlay on the image

            display_str = (self.labels[output_dict.get('detection_classes_' + str(i))] + ": " + str(
                output_dict.get('detection_scores_' + str(i))) + "%")

            frame = visualize_output.draw_bounding_box(
                y1, x1, y2, x2,
                frame,
                thickness=4,
                color=(255, 255, 0),
                display_str=display_str)
            cv2.putText(frame, 'FPS:' + str(fps), (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2,
                        cv2.LINE_AA)
        #        cv2.putText(frame, direction, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,0,255),3)
        #    print( '\n' )

        # If a display is available, show the image on which inference was performed
        self.counter += 1
        if self.display == "on":
            cv2.imshow('NCS live inference', frame)

        # need to save to redis.
        elapsedtime = time.time() - self.starttime
        save = {"elapsedtime": "{0:.2f}".format(elapsedtime), "CPU": str(cpu),
                "inftime": str("{0:.2f}".format(inftime)), "fps": str("{0:.2f}".format(fps)),
                "numberofobjects": str(numobj), "a": str(a)}

        self.redis_db.hmset(self.counter, save)
        self.logfile.write(str(self.counter))
        self.logfile.write(str(save)+"\n")
        #print(self.redis_db.hgetall(self.counter))
        # print(save)
        # need plots...! for multiple objects
        del (a)
        return numobj

    #
    # Existing Work 1 (E1): sending only raw images
    #
    def img_ssd_send_raw_image(self):
        framecnt = 0
        prev_time = 0
        # make ncs connection
        device = self.open_ncs_device()
        graph = load_graph(self.graph_file, device)

        # Main loop: Capture live stream & send frames to NCS
        if self.live == 1:

            while (True):
                ret, frame = self.camera.read()
                #### get fps
                
                prev_time, fps = self.getfps(prev_time)
                print("estimated live fps {0}".format(fps))
                img = self.pre_process_image(frame)
                smallerimg = cv2.resize(img, (self.width, self.height))
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory()
                # log here.
                self.logfile.write(str(framecnt)+"\t"+str(sys.getsizeof(smallerimg))+"\t"+str(cpu)+"\n")
                jsonified_data = MessageBus.create_message_list_numpy(smallerimg, framecnt, encode_param, self.device_name,self.timegap)
                self.msg_bus.send_message_str(self.controller_ip, self.controller_port, jsonified_data)
                framecnt += 1


                # Display the frame for 5ms, and close the window so that the next
                # frame can be displayed. Close the window if 'q' or 'Q' is pressed.
                
                if (cv2.waitKey(1) & 0xFF == ord('q')):
                    break

            self.close_ncs_device(device, graph)
        # sy: read video from file
        else:
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
            cap = cv2.VideoCapture(self.live)

            while cap.isOpened():
#                curTime = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
                curTime=datetime.utcnow().strftime('%H:%M:%S.%f')
                ret, frame = cap.read()  # ndarray
                prev_time, fps = self.getfps(prev_time)
                print("estimated transmission fps {0}".format(fps))
                img = self.pre_process_image(frame)
                #result, encimg = cv2.imencode('.jpg', smallerimg, encode_param)
                if (ret!=1):
                    self.logfile.close()
                    sys.exit(0)
            
                smallerimg = cv2.resize(img, (self.width, self.height))
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory()
                # log here.
                self.logfile.write(str(framecnt)+"\t"+str(sys.getsizeof(smallerimg))+"\t"+str(cpu)+"\n")
                jsonified_data = MessageBus.create_message_list_numpy(smallerimg, framecnt, encode_param, self.device_name,self.timegap)
                self.msg_bus.send_message_str(self.controller_ip, self.controller_port, jsonified_data)
                framecnt += 1

                if (cv2.waitKey(3) & 0xFF == ord('q')):
                    break
#            cap.release()


#
# existing work e2
#
    @threaded
    def img_ssd_save_send_metadata(self):
        framecnt = 0
        prev_time = 0

        # make ncs connection
        device = self.open_ncs_device()
        graph = load_graph(self.graph_file, device)

        # Main loop: Capture live stream & send frames to NCS
        if self.live == 1:
            while (True):
                ret, frame = self.camera.read()
                #### get fps
                prev_time, fps = getfps(prev_time)

                print("estimated live fps {0}".format(fps))
                img = self.pre_process_image(frame)
                # this is spencers code for infering fps.
                self.infer_image_fps(graph, img, frame, fps)

                # Display the frame for 5ms, and close the window so that the next
                # frame can be displayed. Close the window if 'q' or 'Q' is pressed.
                if (cv2.waitKey(1) & 0xFF == ord('q')):
                    break

            self.close_ncs_device(device, graph)

        else:
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
            cap = cv2.VideoCapture(self.live)

            while cap.isOpened():
                curr_time_str = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
                ret, frame = cap.read()  # ndarray
                smallerimg = cv2.resize(frame, (self.width, self.height))
                # result, encimg = cv2.imencode('.jpg', smallerimg, encode_param)


                # TODO: Capture contexts.
                #### get fps
                prev_time, fps = self.getfps(prev_time)
                print("estimated video fps {0}".format(fps))
                img = self.pre_process_image(smallerimg)
                self.infer_image_fps(graph, img, smallerimg, fps)

                self.img_ssd_send_metadata(framecnt)
                framecnt += 1
                if (cv2.waitKey(3) & 0xFF == ord('q')):
                    break
#            cap.release()

    def img_ssd_send_metadata(self, framecnt):
#        print('[Hypervisor] Existing work 2: load and send metadata')
        localNow = datetime.utcnow()+self.timegap
        curTime = localNow.strftime('%H:%M:%S.%f') # string format
        # load metadata from Redis
        save=self.redis_db.hgetall(self.counter)
        save.update({'type': 'img_metadata'})
        save.update({'framecnt': framecnt})
        save.update({'time': curTime})
        print(save)
#            contexts = {'a': 'a'}

            
#            curr_time_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(' -', curTime)
#            metadata_json = {'type': 'img_metadata', 'device_name': self.device_name, 'context': contexts, 'time': curTime}
        self.msg_bus.send_message_json(self.controller_ip, self.controller_port, save)
        time.sleep(0.001)

    @threaded
    def tracking_objects(self):
        framecnt = 0
        prev_time = 0

        # make ncs connection
        device = self.open_ncs_device()
        graph = load_graph(self.graph_file, device)

        # Main loop: Capture live stream & send frames to NCS
        if self.live == 1:
            while (True):
                ret, frame = self.camera.read()
                #### get fps
                prev_time, fps = getfps(prev_time)

                print("estimated live fps {0}".format(fps))
                img = self.pre_process_image(frame)
                # this is spencers code for infering fps.
                # self.infer_image_fps(graph, img, frame, fps)

                # Display the frame for 5ms, and close the window so that the next
                # frame can be displayed. Close the window if 'q' or 'Q' is pressed.
                if (cv2.waitKey(1) & 0xFF == ord('q')):
                    break

            self.close_ncs_device(device, graph)

        else:
            # tracks objects of only one frame.
            # self.track_from_frame(graph) 
            # detects objects every 10 frames, tracks every frames.
            self.periodic_tracking(graph)

    def periodic_tracking(self, graph):

        prev_time = 0
        framecnt = 0
        labels = []
#        trackers = []
#        positions = []

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        cap = cv2.VideoCapture(self.live)

        while cap.isOpened():
            curr_time_str = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
            ret, frame = cap.read()  # ndarray
            if frame is None:
                break
            frame = cv2.resize(frame, (self.width, self.height))
            img = self.pre_process_image(frame)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            prev_time, fps = self.getfps(prev_time)
            print("estimated video fps {0}".format(fps))
            
            positions = []
            if self.counter % self.frame_skips ==0:
                graph.LoadTensor(img, 'user object')

                # Get the results from NCS
                output, userobj = graph.GetResult()
                inference_time = graph.GetGraphOption(mvnc.GraphOption.TIME_TAKEN)

                # Deserialize the output into a python dictionary
                output_dict = deserialize_output.ssd(
                    output,
                    self.confidence_threshold,
                    frame.shape)

                self.tracker_direction(frame, output_dict)
                numobj = (output_dict['num_detections'])

                for i in range(0, output_dict['num_detections']):
                    print("%3.1f%%\t" % output_dict['detection_scores_' + str(i)]
                          + self.labels[int(output_dict['detection_classes_' + str(i)])]
                         + ": Top Left: " + str(output_dict['detection_boxes_' + str(i)][0])
                        + " Bottom Right: " + str(output_dict['detection_boxes_' + str(i)][1]))
                    (y1, x1) = output_dict.get('detection_boxes_' + str(i))[0]
                    (y2, x2) = output_dict.get('detection_boxes_' + str(i))[1]

                    display_str = (self.labels[output_dict.get('detection_classes_' + str(i))] + ": " + str(output_dict.get('detection_scores_' + str(i))) + "%")
                    inftime = np.sum(inference_time)

                    frame = visualize_output.draw_bounding_box(y1, x1, y2, x2, frame, thickness=4, color=(255, 255, 0), display_str=display_str)
                    cv2.putText(frame, 'FPS:' + str(fps), (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

            else:
                for tracker in self.trackers:
                    tracker.update(frame)
                    pos = tracker.get_position()
                    startX = int(pos.left())
                    startY = int(pos.top())
                    endX = int(pos.right())
                    endY = int(pos.bottom())
                    positions.append((startX, startY, endX, endY))
                    print ("Tracking " + str(startX) + " " + str(startY))

            objects = self.ct.update(positions)

            for (objectID, centroid) in objects.items():
                to = self.trackableObjects.get(objectID, None)

                if to == None:
                    to = trackableobject.TrackableObject(objectID, centroid)
                else:
                    y = [c[1] for c in to.centroids]
                    direction = centroid[1] - np.mean(y)
                    to.centroids.append(centroid)
                    if not to.counted:
                        if direction < 0:
                            print("going up")
                        elif direction > 0:
                            print("going down")
                self.trackableObjects[objectID] = to

            self.counter += 1
#            cv2.imwrite('frame'+str(self.counter)+'.jpg', frame)
            if self.display == "on":
                cv2.imshow('NCS live inference', frame)
            if(cv2.waitKey(3) & 0xFF == ord('q')):
                break
        cap.release()


    def tracker_direction(self,rgb, output_dict):
        self.trackers = []
        for i in range(0, output_dict['num_detections']):
            (startY, startX) = output_dict.get('detection_boxes_' + str(i))[0]
            (endY, endX) = output_dict.get('detection_boxes_' + str(i))[1]
            print("detected " + str(startX)+" "+str(startY))
            tracker = dlib.correlation_tracker()
            rect = dlib.rectangle(startX, startY, endX, endY)
            tracker.start_track(rgb,rect)
            self.trackers.append(tracker)

    def track_from_frame(self, graph):
        prev_time = 0
        framecnt = 0
        labels = []
        trackers = []

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        cap = cv2.VideoCapture(self.live)

        while cap.isOpened():
            curr_time_str = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
            ret, frame = cap.read()  # ndarray
            if frame is None:
                break
            frame = cv2.resize(frame, (self.width, self.height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            prev_time, fps = self.getfps(prev_time)
            print("estimated video fps {0}".format(fps))


#            if len(trackers) ==0:
#                (h,w) = frame.shape[:2]
#                blob = cv2.dnn.blobFromImage(frame, 0.007843, (w,h), 127.5)
#            net.setinput(blob)
#            detections = net.forward()
            if len(trackers) ==0:
                img = self.pre_process_image(frame)
                graph.LoadTensor(img, 'user object')

                # Get the results from NCS
                output, userobj = graph.GetResult()

                # Get execution time
                inference_time = graph.GetGraphOption(mvnc.GraphOption.TIME_TAKEN)

                # Deserialize the output into a python dictionary
                output_dict = deserialize_output.ssd(output, self.confidence_threshold, frame.shape)

                inftime = np.sum(inference_time)
                print("inf time: ", inftime)
                numobj = (output_dict['num_detections'])
                # does not matter how many objects are in the frame.. :(
                for i in np.arange(0, output_dict['num_detections']):
                    print("%3.1f%%\t" % output_dict['detection_scores_' + str(i)]
                          + self.labels[int(output_dict['detection_classes_' + str(i)])]
                          + ": Top Left: " + str(output_dict['detection_boxes_' + str(i)][0])
                          + " Bottom Right: " + str(output_dict['detection_boxes_' + str(i)][1]))
                    if output_dict['detection_scores_' + str(i)] > self.confidence_threshold :
                        if output_dict ['detection_classes_'+str(i)] != 15: # skip if not human
                            continue
                        boxxy = output_dict['detection_boxes_'+str(i)][0] # Y1, X1
                        boxxy += (output_dict['detection_boxes_'+str(i)][1]) #Y2, X2
                        idx = output_dict['detection_classes_' + str(i)]
                        label = self.labels[idx]
                        (startY, startX, endY, endX) = boxxy
                        t = dlib.correlation_tracker()
                        rect = dlib.rectangle(startX, startY, endX, endY)
                        t.start_track(rgb, rect)
                        labels.append(label)
                        trackers.append(t)
                        cv2.rectangle(frame, (startX, startY), (endX, endY), (0,255,0),2)

                        cv2.putText(frame,label,(startX, startY - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255,0), 2)
                    
            else:
                for (t, l) in zip(trackers, labels):
                    t.update(rgb)
                    pos = t.get_position()

                    startX = int(pos.left())
                    startY = int(pos.top())
                    endX = int(pos.right())
                    endY = int(pos.bottom())

                cv2.rectangle(frame, (startX, startY), (endX, endY), (0, 255, 0),2)
                cv2.putText(frame, l, (startX, startY-15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,0),2)

            cv2.imshow("Frame", frame)
            framecnt += 1
            if (cv2.waitKey(3) & 0xFF == ord('q')):
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="IoT Camera (device) of Chameleon.")
    parser.add_argument('-i', '--iface', type=str,
                        default='eth0',
                        help="A network interface name for edge network connection (eth0, wlan0, ...)")
    parser.add_argument('-g', '--graph', type=str,
                        default='../SSD_MobileNet/graph',
                        help="Absolute path to the neural network graph file.")
    parser.add_argument('-l', '--labels', type=str,
                        default='../SSD_MobileNet/labels.txt',
                        help="Absolute path to labels file.")
    parser.add_argument('-tr', '--transmission', type=str,
                        default="e1",
                        help="frame transmission options (proposed=p, existing_1=e1, ...)")
    parser.add_argument('-w', '--width', type=int,
                        default="600",
                        help="width of the capturing videos.")
    parser.add_argument('-hi', '--height', type=int,
                        default="400",
                        help="height of the capturing videos.")
    parser.add_argument('-vf', '--videofile', type=str,
                        default="1",
                        help="load from video file.")
    parser.add_argument('-dis', '--display', type=str,
                        default="off",
                        help="load from video file.")
    parser.add_argument('-D', '--dim', type=int,
                        nargs='+',
                        default=[224, 224],
                        help="Image dimensions. ex. -D 224 224")
    parser.add_argument('-c', '--colormode', type=str,
                        default="bgr",
                        help="RGB vs BGR color sequence. This is network dependent.")
    parser.add_argument('-ln', '--logname', type=str,
                        default='logfile.txt',
                        help="your log filename name.")

    ARGS = parser.parse_args()

    # Read 'camera.ini'
    config = configparser.ConfigParser()
    config.read('../../resource/config/camera_823_main.ini')

    # Hypervisor initialization and connection
    controller_ip = config['message_bus']['controller_ip']
    controller_port = config['message_bus']['controller_port']
    device_name = config['message_bus']['device_name']
    device_port = config['message_bus']['device_port']
    device_ip_ext = config['message_bus']['device_ip_ext']
    device_port_ext = config['message_bus']['device_port_ext']
    hyp = Hypervisor(device_name, device_port, device_ip_ext, device_port_ext, ARGS.iface, controller_ip, controller_port, ARGS.videofile, ARGS.transmission)
    hyp.join()

    # Camera-related settings
    hyp.display = ARGS.display
    hyp.graph_file = ARGS.graph
    hyp.width = ARGS.width
    hyp.height = ARGS.height
    hyp.confidence_threshold = float(config['Parameter']['confidence_threshold'])
    hyp.color_mode = config['Parameter']['color_mode']
    hyp.dimensions = ast.literal_eval(config['Parameter']['dimensions'])
    hyp.mean = ast.literal_eval(config['Parameter']['mean'])
    hyp.scale = float(config['Parameter']['scale'])
    hyp.connect_redis_db(6379)
    hyp.load_labels(ARGS.labels)
    hyp.logfile = open(ARGS.logname, 'w')
    hyp.ct = centroidtracker.CentroidTracker(maxDisappeared=40, maxDistance =50)

    # Operations based on scheme options
    if ARGS.transmission == 'p':
        print('[Hypervisor] running our proposed scheme.')
        #not properly imp
    elif ARGS.transmission == 'e1':
        print('[Hypervisor] running as an existing work 1. (raw image stream)')
        # Run video analytics with SSD
        hyp.img_ssd_send_raw_image()
        hyp.logfile.close()
        
    elif ARGS.transmission == 'e2': # what is meta data? 
        print('[Hypervisor] running as an existing work 2. (image metadata)') 
        hyp.img_ssd_save_send_metadata()
#        hyp.logfile.close()
        
    elif ARGS.transmission == 'e3':
        print('[Hypervisor] running as an existing work 3.')
        hyp.logfile.close()
    elif ARGS.transmission == 'tracking':
        print('[Hypervisor] tracking objects.')
        hyp.tracking_objects()
        hyp.logfile.close()
    else:
        print('[Hypervisor] Error: invalid option for the scheme.')
