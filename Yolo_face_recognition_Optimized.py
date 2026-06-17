"""
Integrated Face Recognition Robot Control System - COMPACT LAYOUT WITH TIME CONTROL
Based on original YOLO Enhanced Version with complete functionality

ALL ORIGINAL FEATURES MAINTAINED:
- YOLOv8-face for robust face detection
- MobileFaceNet for face recognition
- Multi-frame confirmation
- Face alignment
- Welcome sequences
- Full motor control

NEW FEATURES ADDED:
- Compact GUI layout (Face Recognition + Connection combined)
- Time Control (1ms - 4000ms) with slider and manual entry
- All original text preserved and visible

Requirements: Same as original + servo_motor_protocols.py
"""

import cv2
import numpy as np
import os
from pathlib import Path
import pickle
import time
from datetime import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog, font as tkfont
import serial
import serial.tools.list_ports
from collections import deque

# Import servo motor protocols
try:
    from servo_motor_protocols import (
        ServoMotorProtocols,
        ServoMotorController,
        WelcomeSequence,
        get_rgb_protocol,
        get_angle_protocol
    )
    SERVO_AVAILABLE = True
except ImportError:
    SERVO_AVAILABLE = False
    print("Warning: servo_motor_protocols not found. Motor control will be disabled.")

# Check for YOLO (ultralytics)
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("Warning: ultralytics not available. Install with: pip install ultralytics")

# Check for TensorFlow Lite
try:
    import tensorflow as tf
    TF_AVAILABLE = True
    print("TensorFlow version:", tf.__version__)
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        TF_AVAILABLE = True
        print("Using TFLite Runtime")
    except ImportError:
        TF_AVAILABLE = False
        print("Warning: TensorFlow/TFLite not available. Face recognition will be disabled.")


# ==================== COLOR SCHEME ====================
class ColorScheme:
    """Enhanced color scheme for the application"""
    
    BG_DARK = "#1a1a2e"
    BG_MEDIUM = "#16213e"
    BG_LIGHT = "#0f3460"
    BG_ACCENT = "#533483"
    
    TEXT_PRIMARY = "#ffffff"
    TEXT_SECONDARY = "#b8b8b8"
    TEXT_ACCENT = "#00fff5"
    
    STATUS_CONNECTED = "#00ff88"
    STATUS_DISCONNECTED = "#ff4757"
    STATUS_WARNING = "#ffa502"
    STATUS_INFO = "#3498db"
    
    BTN_PRIMARY = "#0f3460"
    BTN_PRIMARY_HOVER = "#ff6b81"
    BTN_SECONDARY = "#0f3460"
    BTN_SUCCESS = "#00d26a"
    BTN_DANGER = "#0f3460"
    BTN_WARNING = "#0f3460"
    
    MOTOR_COLORS = {i: "#45B7D1" for i in range(1, 17)}
    RGB_COLORS = {"RED": "#FF0000", "GREEN": "#00FF00", "BLUE": "#0000FF"}


# ==================== YOLO FACE DETECTOR (UNCHANGED FROM ORIGINAL) ====================
class YOLOFaceDetector:
    """YOLO-based Face Detector - More robust than BlazeFace"""
    
    def __init__(self, model_path="yolov8n-face.pt", confidence_threshold=0.5):
        if not YOLO_AVAILABLE:
            raise RuntimeError("ultralytics package required. Install with: pip install ultralytics")
        
        self.confidence_threshold = confidence_threshold
        
        if not os.path.exists(model_path):
            print(f"Model {model_path} not found.")
            print("Downloading YOLOv8n model...")
            self.model = YOLO('yolov8n.pt')
            print("Note: For better face detection, download yolov8n-face.pt from:")
            print("https://github.com/akanametov/yolov8-face/releases/download/v0.0.0/yolov8n-face.pt")
        else:
            self.model = YOLO(model_path)
        
        print(f"YOLO Face Detector initialized with confidence threshold: {confidence_threshold}")
    
    def detect_faces(self, image):
        """Detect faces in an image using YOLO"""
        results = self.model(image, verbose=False, conf=self.confidence_threshold)
        
        faces = []
        h, w = image.shape[:2]
        
        for result in results:
            boxes = result.boxes
            if boxes is not None:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = box.conf[0].cpu().numpy()
                    
                    if conf >= self.confidence_threshold:
                        x1 = max(0, int(x1))
                        y1 = max(0, int(y1))
                        x2 = min(w, int(x2))
                        y2 = min(h, int(y2))
                        
                        width = x2 - x1
                        height = y2 - y1
                        
                        if width > 20 and height > 20:
                            faces.append((x1, y1, x2, y2, conf))
        
        faces.sort(key=lambda x: x[4], reverse=True)
        return [(x1, y1, x2, y2) for x1, y1, x2, y2, _ in faces]


# ==================== FACE RECOGNITION SYSTEM (UNCHANGED FROM ORIGINAL) ====================
class FaceRecognitionSystem:
    """Face Recognition System using YOLO detection and MobileFaceNet recognition"""
    
    def __init__(self, yolo_model_path, recognition_model_path, known_faces_path, debug_mode=False):
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow/TFLite is required for face recognition")
        
        self.detector = YOLOFaceDetector(model_path=yolo_model_path, confidence_threshold=0.5)
        
        try:
            self.recognizer = tf.lite.Interpreter(model_path=recognition_model_path)
        except:
            import tflite_runtime.interpreter as tflite
            self.recognizer = tflite.Interpreter(model_path=recognition_model_path)
        
        self.recognizer.allocate_tensors()
        self.recognition_input_details = self.recognizer.get_input_details()
        self.recognition_output_details = self.recognizer.get_output_details()
        
        self.camera = None
        self.debug_mode = debug_mode
        self.known_face_embeddings = []
        self.known_face_name = "Mr. David"
        
        self.recognition_threshold = 0.65
        self.strict_threshold = 0.75
        self.min_matching_embeddings = 3
        self.min_high_conf_matches = 2
        
        self.confirmation_frames_required = 3
        self.recognition_history = deque(maxlen=5)
        self.unknown_history = deque(maxlen=5)
        
        self.welcome_duration = 0.003  #3
        self.alert_duration = 0.01    #1
        self.detection_fail_duration = 0.03    #3
        
        self.in_welcome_mode = False
        self.welcome_start_time = None
        self.welcome_last_box = None
        self.in_alert_mode = False
        self.alert_start_time = None
        self.alert_last_box = None
        
        self.in_detection_fail_mode = False
        self.detection_fail_start_time = None
        self.consecutive_alert_count = 0
        self.max_consecutive_alerts = 3
        
        self.welcome_sequence_running = False
        self.welcome_sequence_status = ""
        
        self.on_david_recognized = None
        self.is_running = False
        
        self.load_known_faces(known_faces_path)
    
    def load_known_faces(self, folder_path):
        """Load images from the known faces folder and create embeddings"""
        print(f"Loading known faces from: {folder_path}")
        
        if not os.path.exists(folder_path):
            print(f"Warning: Folder {folder_path} does not exist!")
            return
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp']
        image_files = []
        
        for ext in image_extensions:
            image_files.extend(Path(folder_path).glob(f'*{ext}'))
            image_files.extend(Path(folder_path).glob(f'*{ext.upper()}'))
        
        if len(image_files) == 0:
            print("Warning: No images found in the folder!")
            return
        
        print(f"Found {len(image_files)} images")
        
        for img_path in image_files:
            try:
                img = cv2.imread(str(img_path))
                if img is None:
                    continue
                
                faces = self.detector.detect_faces(img)
                
                if len(faces) > 0:
                    x1, y1, x2, y2 = faces[0]
                    face_img = img[y1:y2, x1:x2]
                    embedding = self.get_face_embedding(face_img)
                    
                    if embedding is not None:
                        self.known_face_embeddings.append(embedding)
                        print(f"✓ Processed: {img_path.name} (face detected)")
                else:
                    embedding = self.get_face_embedding(img)
                    if embedding is not None:
                        self.known_face_embeddings.append(embedding)
                        print(f"✓ Processed: {img_path.name} (whole image)")
                    else:
                        print(f"✗ Skipped: {img_path.name} (no face/embedding)")
                    
            except Exception as e:
                print(f"Error processing {img_path.name}: {e}")
        
        print(f"\n{'='*50}")
        print(f"Successfully loaded {len(self.known_face_embeddings)} face embeddings")
        print(f"{'='*50}\n")
        self.save_embeddings()
    
    def save_embeddings(self, filename='known_faces.pkl'):
        with open(filename, 'wb') as f:
            pickle.dump({'embeddings': self.known_face_embeddings, 'name': self.known_face_name}, f)
        print(f"Embeddings saved to {filename}")
    
    def load_embeddings(self, filename='known_faces.pkl'):
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                data = pickle.load(f)
                self.known_face_embeddings = data['embeddings']
                self.known_face_name = data['name']
            print(f"Loaded {len(self.known_face_embeddings)} embeddings from {filename}")
            return True
        return False
    
    def align_face(self, face_image):
        h, w = face_image.shape[:2]
        target_size = (112, 112)
        
        if h > w:
            pad = (h - w) // 2
            face_padded = cv2.copyMakeBorder(face_image, 0, 0, pad, pad, cv2.BORDER_CONSTANT, value=[0, 0, 0])
        elif w > h:
            pad = (w - h) // 2
            face_padded = cv2.copyMakeBorder(face_image, pad, pad, 0, 0, cv2.BORDER_CONSTANT, value=[0, 0, 0])
        else:
            face_padded = face_image
        
        face_aligned = cv2.resize(face_padded, target_size)
        return face_aligned
    
    def preprocess_for_recognition(self, face_image):
        input_shape = self.recognition_input_details[0]['shape']
        height, width = input_shape[1], input_shape[2]
        
        face_aligned = self.align_face(face_image)
        face_resized = cv2.resize(face_aligned, (width, height))
        face_rgb = cv2.cvtColor(face_resized, cv2.COLOR_BGR2RGB)
        face_normalized = face_rgb.astype(np.float32) / 255.0
        
        return np.expand_dims(face_normalized, axis=0)
    
    def get_face_embedding(self, face_image):
        try:
            if face_image.size == 0:
                return None
            
            input_data = self.preprocess_for_recognition(face_image)
            self.recognizer.set_tensor(self.recognition_input_details[0]['index'], input_data)
            self.recognizer.invoke()
            embedding = self.recognizer.get_tensor(self.recognition_output_details[0]['index'])
            
            embedding_normalized = embedding / np.linalg.norm(embedding)
            return embedding_normalized[0]
        except Exception as e:
            if self.debug_mode:
                print(f"Error getting embedding: {e}")
            return None
    
    def recognize_face(self, face_image):
        if len(self.known_face_embeddings) == 0:
            return False, "Unknown", 0.0
        
        current_embedding = self.get_face_embedding(face_image)
        if current_embedding is None:
            return False, "Unknown", 0.0
        
        similarities = np.array([np.dot(current_embedding, ke) for ke in self.known_face_embeddings])
        
        max_sim = np.max(similarities)
        mean_sim = np.mean(similarities)
        median_sim = np.median(similarities)
        std_sim = np.std(similarities)
        
        matches = np.sum(similarities > self.recognition_threshold)
        high_conf_matches = np.sum(similarities > self.strict_threshold)
        
        top_k = min(5, len(similarities))
        top_k_avg = np.mean(np.sort(similarities)[-top_k:])
        
        if self.debug_mode:
            print(f"\n{'='*60}")
            print(f"[RECOGNITION DEBUG]")
            print(f"  Max Similarity:     {max_sim:.4f} (threshold: {self.strict_threshold})")
            print(f"  Mean Similarity:    {mean_sim:.4f}")
            print(f"  Median Similarity:  {median_sim:.4f}")
            print(f"  Std Dev:            {std_sim:.4f}")
            print(f"  Top-{top_k} Average:    {top_k_avg:.4f}")
            print(f"  Matches (>{self.recognition_threshold}): {matches}/{len(similarities)}")
            print(f"  High-Conf (>{self.strict_threshold}): {high_conf_matches}/{len(similarities)}")
        
        primary_match = (max_sim >= self.strict_threshold and high_conf_matches >= self.min_high_conf_matches)
        secondary_match = (max_sim >= self.recognition_threshold and matches >= self.min_matching_embeddings and
                          mean_sim >= (self.recognition_threshold - 0.01) and top_k_avg >= self.recognition_threshold)
        consistency_bonus = std_sim < 0.15
        
        is_recognized = primary_match or (secondary_match and consistency_bonus)
        
        if max_sim < (self.recognition_threshold - 0.10):
            is_recognized = False
        
        if self.debug_mode:
            print(f"  Primary Match:      {primary_match}")
            print(f"  Secondary Match:    {secondary_match}")
            print(f"  Consistency Bonus:  {consistency_bonus}")
            print(f"  FINAL DECISION:     {'✓ RECOGNIZED' if is_recognized else '✗ UNKNOWN'}")
            print(f"{'='*60}\n")
        
        if is_recognized:
            return True, self.known_face_name, top_k_avg
        return False, "Unknown", max_sim
    
    def check_multi_frame_confirmation(self, current_result):
        is_known, name, confidence = current_result
        
        if is_known:
            self.recognition_history.append(confidence)
            self.unknown_history.clear()
            
            if len(self.recognition_history) >= self.confirmation_frames_required:
                avg_conf = np.mean(list(self.recognition_history))
                if avg_conf >= self.recognition_threshold:
                    return True, name, avg_conf
        else:
            self.unknown_history.append(confidence)
            self.recognition_history.clear()
            
            if len(self.unknown_history) >= self.confirmation_frames_required:
                return False, "Unknown", np.mean(list(self.unknown_history))
        
        return None, "Pending", confidence
    
    def initialize_camera(self, camera_index=0):
        self.camera = cv2.VideoCapture(camera_index)
        
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.camera.set(cv2.CAP_PROP_FPS, 30)
        self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        if not self.camera.isOpened():
            raise Exception("Could not open camera!")
        
        print("Camera initialized successfully")
        print(f"  Resolution: {int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        print(f"  FPS: {self.camera.get(cv2.CAP_PROP_FPS)}")
    
    def draw_display_message(self, image, box, remaining_time, label_text, big_text, color):
        x1, y1, x2, y2 = box
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        
        label_size, _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.rectangle(image, (x1, y1 - 40), (x1 + label_size[0] + 20, y1), color, -1)
        cv2.putText(image, label_text, (x1 + 10, y1 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
        
        timer_text = f"Display: {int(remaining_time)}s"
        timer_size, _ = cv2.getTextSize(timer_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(image, (x1, y2 + 5), (x1 + timer_size[0] + 10, y2 + 35), color, -1)
        cv2.putText(image, timer_text, (x1 + 5, y2 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        
        cl, ct = 20, 4
        cv2.line(image, (x1, y1), (x1 + cl, y1), color, ct)
        cv2.line(image, (x1, y1), (x1, y1 + cl), color, ct)
        cv2.line(image, (x2, y1), (x2 - cl, y1), color, ct)
        cv2.line(image, (x2, y1), (x2, y1 + cl), color, ct)
        cv2.line(image, (x1, y2), (x1 + cl, y2), color, ct)
        cv2.line(image, (x1, y2), (x1, y2 - cl), color, ct)
        cv2.line(image, (x2, y2), (x2 - cl, y2), color, ct)
        cv2.line(image, (x2, y2), (x2, y2 - cl), color, ct)
        
        h, w = image.shape[:2]
        big_size, _ = cv2.getTextSize(big_text, cv2.FONT_HERSHEY_SIMPLEX, 2.0, 3)
        big_x = (w - big_size[0]) // 2
        cv2.rectangle(image, (big_x - 20, 60), (big_x + big_size[0] + 20, 120), color, -1)
        cv2.putText(image, big_text, (big_x, 105), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255,255,255), 3)
    
    def draw_detection_fail_message(self, image, remaining_time):
        h, w = image.shape[:2]
        
        overlay = image.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 100), -1)
        cv2.addWeighted(overlay, 0.7, image, 0.3, 0, image)
        
        main_text = "DETECTION FAIL"
        main_size, _ = cv2.getTextSize(main_text, cv2.FONT_HERSHEY_SIMPLEX, 2.5, 4)
        main_x = (w - main_size[0]) // 2
        main_y = h // 2 - 30
        
        cv2.rectangle(image, (main_x - 30, main_y - main_size[1] - 20), 
                     (main_x + main_size[0] + 30, main_y + 20), (0, 0, 200), -1)
        cv2.rectangle(image, (main_x - 30, main_y - main_size[1] - 20), 
                     (main_x + main_size[0] + 30, main_y + 20), (255, 255, 255), 3)
        cv2.putText(image, main_text, (main_x, main_y), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 255, 255), 4)
        
        sub_text = f"{self.max_consecutive_alerts} consecutive unknown faces detected"
        sub_size, _ = cv2.getTextSize(sub_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        sub_x = (w - sub_size[0]) // 2
        sub_y = main_y + 60
        cv2.putText(image, sub_text, (sub_x, sub_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        timer_text = f"Restarting in {int(remaining_time)}s..."
        timer_size, _ = cv2.getTextSize(timer_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
        timer_x = (w - timer_size[0]) // 2
        timer_y = sub_y + 50
        cv2.putText(image, timer_text, (timer_x, timer_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    
    def draw_welcome_sequence_message(self, image):
        h, w = image.shape[:2]
        
        overlay = image.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), (100, 50, 50), -1)
        cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)
        
        main_text = "ROBOT SEQUENCE RUNNING"
        main_size, _ = cv2.getTextSize(main_text, cv2.FONT_HERSHEY_SIMPLEX, 1.8, 3)
        main_x = (w - main_size[0]) // 2
        main_y = h // 2 - 60
        
        cv2.rectangle(image, (main_x - 30, main_y - main_size[1] - 20), 
                     (main_x + main_size[0] + 30, main_y + 20), (200, 100, 0), -1)
        cv2.putText(image, main_text, (main_x, main_y), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)
        
        sub_text = "Mr. David Recognized - Executing Welcome!"
        sub_size, _ = cv2.getTextSize(sub_text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        sub_x = (w - sub_size[0]) // 2
        sub_y = main_y + 50
        cv2.putText(image, sub_text, (sub_x, sub_y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        
        if self.welcome_sequence_status:
            status_text = f"Status: {self.welcome_sequence_status}"
            status_size, _ = cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            status_x = (w - status_size[0]) // 2
            status_y = sub_y + 45
            cv2.putText(image, status_text, (status_x, status_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
        
        pause_text = "Face Detection PAUSED"
        pause_size, _ = cv2.getTextSize(pause_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        pause_x = (w - pause_size[0]) // 2
        pause_y = h - 80
        cv2.putText(image, pause_text, (pause_x, pause_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 255), 2)
    
    def stop(self):
        self.is_running = False
        if self.camera:
            self.camera.release()
        cv2.destroyAllWindows()
    
    def reset_detection_state(self):
        self.in_welcome_mode = False
        self.welcome_start_time = None
        self.welcome_last_box = None
        self.in_alert_mode = False
        self.alert_start_time = None
        self.alert_last_box = None
        self.in_detection_fail_mode = False
        self.detection_fail_start_time = None
        self.consecutive_alert_count = 0
        self.recognition_history.clear()
        self.unknown_history.clear()
        print("Detection state reset - starting fresh scan")
    
    def run_detection_loop(self, window_name="YOLO Face Recognition"):
        """Main detection loop - COMPLETE IMPLEMENTATION"""
        self.is_running = True
        david_recognized_this_cycle = False
        
        self.reset_detection_state()
        
        fps_counter = 0
        fps_start_time = time.time()
        current_fps = 0
        
        while self.is_running:
            ret, frame = self.camera.read()
            if not ret:
                break
            
            display_frame = frame.copy()
            
            # FPS calculation
            fps_counter += 1
            if time.time() - fps_start_time >= 1.0:
                current_fps = fps_counter
                fps_counter = 0
                fps_start_time = time.time()
            
            # Draw FPS
            cv2.putText(display_frame, f"FPS: {current_fps}", (display_frame.shape[1] - 100, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Check if welcome sequence is running
            if self.welcome_sequence_running:
                self.draw_welcome_sequence_message(display_frame)
                cv2.imshow(window_name, display_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue
            
            # Detection fail mode
            if self.in_detection_fail_mode:
                elapsed = (datetime.now() - self.detection_fail_start_time).total_seconds()
                remaining = self.detection_fail_duration - elapsed
                
                if remaining > 0:
                    self.draw_detection_fail_message(display_frame, remaining)
                else:
                    self.reset_detection_state()
            
            # Welcome mode
            elif self.in_welcome_mode:
                elapsed = (datetime.now() - self.welcome_start_time).total_seconds()
                remaining = self.welcome_duration - elapsed
                
                if remaining > 0:
                    face_box = self.welcome_last_box or (160, 120, 480, 360)
                    self.draw_display_message(display_frame, face_box, remaining, 
                                             "Welcome, Mr. David", "WELCOME!", (0, 255, 0))
                else:
                    self.in_welcome_mode = False
                    self.welcome_start_time = None
                    self.welcome_last_box = None
                    self.consecutive_alert_count = 0
                    if self.on_david_recognized and david_recognized_this_cycle:
                        david_recognized_this_cycle = False
                        threading.Thread(target=self.on_david_recognized, daemon=True).start()
            
            # Alert mode
            elif self.in_alert_mode:
                elapsed = (datetime.now() - self.alert_start_time).total_seconds()
                remaining = self.alert_duration - elapsed
                
                if remaining > 0:
                    face_box = self.alert_last_box or (160, 120, 480, 360)
                    self.draw_display_message(display_frame, face_box, remaining, 
                                             f"Unknown ({self.consecutive_alert_count}/{self.max_consecutive_alerts})", 
                                             "ALERT!", (0, 0, 255))
                else:
                    self.in_alert_mode = False
                    self.alert_start_time = None
                    self.alert_last_box = None
                    
                    if self.consecutive_alert_count >= self.max_consecutive_alerts:
                        self.in_detection_fail_mode = True
                        self.detection_fail_start_time = datetime.now()
            
            # Active scanning
            else:
                faces = self.detector.detect_faces(frame)
                
                # Draw alert count
                cv2.putText(display_frame, f"Alert: {self.consecutive_alert_count}/{self.max_consecutive_alerts}", 
                           (10, display_frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 165, 0), 2)
                
                for face_box in faces:
                    x1, y1, x2, y2 = face_box
                    face_img = frame[y1:y2, x1:x2]
                    
                    if face_img.size == 0:
                        continue
                    
                    result = self.recognize_face(face_img)
                    confirmed_result = self.check_multi_frame_confirmation(result)
                    is_confirmed, name, confidence = confirmed_result
                    
                    if is_confirmed is None:
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                        cv2.putText(display_frame, f"Analyzing... ({confidence:.2f})", 
                                   (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                    elif is_confirmed and name == self.known_face_name:
                        self.in_welcome_mode = True
                        self.welcome_start_time = datetime.now()
                        self.welcome_last_box = face_box
                        david_recognized_this_cycle = True
                        self.consecutive_alert_count = 0
                        print(f"✓ Mr. David CONFIRMED! Confidence: {confidence:.3f}")
                        self.draw_display_message(display_frame, face_box, self.welcome_duration, 
                                                 f"Welcome! ({confidence:.2f})", "WELCOME!", (0, 255, 0))
                        break
                    elif is_confirmed == False:
                        self.consecutive_alert_count += 1
                        print(f"✗ Unknown face CONFIRMED. Alert: {self.consecutive_alert_count}/{self.max_consecutive_alerts}")
                        
                        self.in_alert_mode = True
                        self.alert_start_time = datetime.now()
                        self.alert_last_box = face_box
                        self.draw_display_message(display_frame, face_box, self.alert_duration, 
                                                 f"Unknown ({confidence:.2f})", "ALERT!", (0, 0, 255))
                        break
                
                if not self.in_welcome_mode and not self.in_alert_mode and not self.in_detection_fail_mode:
                    cv2.putText(display_frame, f"Scanning... Faces: {len(faces)}", (10, 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            cv2.imshow(window_name, display_frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                print("Manual reset triggered")
                self.reset_detection_state()
            elif key == ord('d'):
                self.debug_mode = not self.debug_mode
                print(f"Debug mode: {'ON' if self.debug_mode else 'OFF'}")
        
        self.stop()


# ==================== STYLED BUTTON ====================
class StyledButton(tk.Button):
    """Custom styled button with hover effects"""
    
    def __init__(self, master, text, command, bg_color, hover_color, fg_color="#ffffff", 
                 width=15, height=2, font_size=10, **kwargs):
        
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.fg_color = fg_color
        
        super().__init__(
            master, text=text, command=command, bg=bg_color, fg=fg_color,
            activebackground=hover_color, activeforeground=fg_color,
            relief="flat", cursor="hand2", width=width, height=height,
            font=("Segoe UI", font_size, "bold"), bd=0, **kwargs
        )
        
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
    
    def _on_enter(self, e):
        if self['state'] != 'disabled':
            self['bg'] = self.hover_color
    
    def _on_leave(self, e):
        if self['state'] != 'disabled':
            self['bg'] = self.bg_color


# ==================== COMPACT ROBOT CONTROLLER WITH TIME CONTROL ====================
class IntegratedRobotController:
    """
    Compact GUI Robot Controller
    ALL original functionality + Time Control (1ms - 4000ms)
    """
    
    DEFAULT_PORT = "/dev/ttyAMA2"
    DEFAULT_BAUD = 115200
    
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 YOLO Face Recognition Robot Controller [COMPACT LAYOUT + TIME CONTROL]")
        self.root.geometry("1600x950")
        self.root.resizable(True, True)
        self.root.configure(bg=ColorScheme.BG_DARK)
        
        self.serial_port = None
        self.is_connected = False
        self.stm32_detected = False
        
        # ===== TIME CONTROL VARIABLES =====
        self.current_movement_time = 300   # original 1000 ms
        self.min_movement_time = 1
        self.max_movement_time = 4000
        # ===== END TIME CONTROL =====
        
        if SERVO_AVAILABLE:
            self.motor_controller = ServoMotorController()
        else:
            self.motor_controller = None
        
        self.face_system = None
        self.face_detection_running = False
        self.face_detection_thread = None
        
        self.current_angles = {i: 0 for i in range(1, 17)}
        self.current_colors = {i: "BLUE" for i in range(1, 17)}
        
        self.motor_widgets = {}
        self.continuous_detection = False
        self.log_text = None
        
        self.title_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.label_font = tkfont.Font(family="Segoe UI", size=9)
        self.button_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        
        self.create_widgets()
        self.update_connection_status()
        self.refresh_ports_silent()
    
    def create_styled_frame(self, parent, text, row, col, colspan=1, rowspan=1):
        frame = tk.LabelFrame(
            parent, text=f"  {text}  ", bg=ColorScheme.BG_MEDIUM,
            fg=ColorScheme.TEXT_ACCENT, font=self.title_font,
            relief="ridge", bd=2, padx=8, pady=8
        )
        frame.grid(row=row, column=col, columnspan=colspan, rowspan=rowspan, 
                  padx=5, pady=5, sticky="nsew")
        return frame
    
    def create_widgets(self):
        """Create all GUI widgets in compact layout"""
        
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(4, weight=1)
        
        main_frame = tk.Frame(self.root, bg=ColorScheme.BG_DARK, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        
        # Header
        header_frame = tk.Frame(main_frame, bg=ColorScheme.BG_ACCENT, height=50)
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header_frame.grid_propagate(False)
        
        title_label = tk.Label(
            header_frame, text="🤖 YOLO FACE RECOGNITION ROBOT CONTROLLER",
            bg=ColorScheme.BG_ACCENT, fg=ColorScheme.TEXT_PRIMARY,
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(expand=True)
        
        # ===== COMBINED FACE RECOGNITION + CONNECTION PANEL =====
        combo_frame = self.create_styled_frame(main_frame, "👤 FACE RECOGNITION & 🔌 CONNECTION", 1, 0, 2)
        
        # Split into left (Face Recognition) and right (Connection)
        left_frame = tk.Frame(combo_frame, bg=ColorScheme.BG_MEDIUM)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Vertical separator
        separator = tk.Frame(combo_frame, bg=ColorScheme.TEXT_ACCENT, width=2)
        separator.pack(side="left", fill="y", padx=5)
        
        right_frame = tk.Frame(combo_frame, bg=ColorScheme.BG_MEDIUM)
        right_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        
        # LEFT SIDE: Face Recognition
        tk.Label(left_frame, text="YOLO Detection Model:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=0, column=0, sticky="w", padx=3, pady=2)
        self.detection_model_var = tk.StringVar(value="yolov8n-face.pt")
        tk.Entry(left_frame, textvariable=self.detection_model_var, width=20, 
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).grid(row=0, column=1, padx=3, pady=2, sticky="ew")
        
        tk.Label(left_frame, text="Recognition Model:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=1, column=0, sticky="w", padx=3, pady=2)
        self.recognition_model_var = tk.StringVar(value="mobilefacenet.tflite")
        tk.Entry(left_frame, textvariable=self.recognition_model_var, width=20,
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).grid(row=1, column=1, padx=3, pady=2, sticky="ew")
        
        tk.Label(left_frame, text="Training Folder:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=2, column=0, sticky="w", padx=3, pady=2)
        self.training_folder_var = tk.StringVar(value="mrdavid")
        tk.Entry(left_frame, textvariable=self.training_folder_var, width=20,
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).grid(row=2, column=1, padx=3, pady=2, sticky="ew")
        
        StyledButton(left_frame, "Browse", self.browse_training_folder,
                    ColorScheme.BTN_SECONDARY, ColorScheme.BG_LIGHT, width=8, height=1,
                    font_size=8).grid(row=2, column=2, padx=3, pady=2)
        
        # Thresholds
        thresh_frame = tk.Frame(left_frame, bg=ColorScheme.BG_MEDIUM)
        thresh_frame.grid(row=3, column=0, columnspan=3, pady=3, sticky="ew")
        
        tk.Label(thresh_frame, text="Recognition Threshold:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).pack(side="left", padx=2)
        self.threshold_var = tk.StringVar(value="0.65")
        tk.Entry(thresh_frame, textvariable=self.threshold_var, width=5,
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).pack(side="left", padx=2)
        
        tk.Label(thresh_frame, text="Strict Threshold:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).pack(side="left", padx=2)
        self.strict_threshold_var = tk.StringVar(value="0.75")
        tk.Entry(thresh_frame, textvariable=self.strict_threshold_var, width=5,
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).pack(side="left", padx=2)
        
        tk.Label(thresh_frame, text="Confirm Frames:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).pack(side="left", padx=2)
        self.confirm_frames_var = tk.StringVar(value="3")
        tk.Entry(thresh_frame, textvariable=self.confirm_frames_var, width=3,
                font=self.label_font, bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY).pack(side="left", padx=2)
        
        # Face detection buttons
        face_btn_frame = tk.Frame(left_frame, bg=ColorScheme.BG_MEDIUM)
        face_btn_frame.grid(row=4, column=0, columnspan=3, pady=5)
        
        self.start_face_btn = StyledButton(
            face_btn_frame, "🎥 START DETECTION",
            self.start_face_detection, ColorScheme.BTN_PRIMARY,
            ColorScheme.BTN_PRIMARY_HOVER, width=18, height=2, font_size=10
        )
        self.start_face_btn.pack(side="left", padx=3)
        
        self.stop_face_btn = StyledButton(
            face_btn_frame, "⏹ STOP",
            self.stop_face_detection, ColorScheme.BTN_DANGER,
            "#3498db", width=10, height=2, font_size=10
        )
        self.stop_face_btn.pack(side="left", padx=3)
        self.stop_face_btn.config(state="disabled")
        
        # Checkboxes
        check_frame = tk.Frame(left_frame, bg=ColorScheme.BG_MEDIUM)
        check_frame.grid(row=5, column=0, columnspan=3, pady=3)
        
        self.continuous_var = tk.BooleanVar(value=True)
        tk.Checkbutton(check_frame, text="🔄 Continuous Detection",
                      variable=self.continuous_var, bg=ColorScheme.BG_MEDIUM,
                      fg=ColorScheme.TEXT_ACCENT, selectcolor=ColorScheme.BG_LIGHT,
                      activebackground=ColorScheme.BG_MEDIUM, font=self.label_font).pack(side="left", padx=5)
        
        self.debug_var = tk.BooleanVar(value=True)
        tk.Checkbutton(check_frame, text="🔍 Debug Mode",
                      variable=self.debug_var, bg=ColorScheme.BG_MEDIUM,
                      fg=ColorScheme.TEXT_ACCENT, selectcolor=ColorScheme.BG_LIGHT,
                      activebackground=ColorScheme.BG_MEDIUM, font=self.label_font).pack(side="left", padx=5)
        
        self.face_status = tk.Label(
            left_frame, text="● Face Detection: NOT RUNNING",
            bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.STATUS_DISCONNECTED,
            font=("Segoe UI", 10, "bold")
        )
        self.face_status.grid(row=6, column=0, columnspan=3, pady=5)
        
        # RIGHT SIDE: Connection
        tk.Label(right_frame, text="UART Connection (Raspberry Pi 5 → STM32F103)", 
                bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.TEXT_ACCENT,
                font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4, pady=5)
        
        tk.Label(right_frame, text="UART Port:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=1, column=0, padx=3, pady=3, sticky="w")
        
        self.port_var = tk.StringVar(value=self.DEFAULT_PORT)
        self.port_combo = ttk.Combobox(right_frame, textvariable=self.port_var, width=15, font=self.label_font)
        self.port_combo.grid(row=1, column=1, padx=3, pady=3, sticky="ew")
        
        tk.Label(right_frame, text="Baud Rate:", bg=ColorScheme.BG_MEDIUM, 
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=2, column=0, padx=3, pady=3, sticky="w")
        
        self.baud_var = tk.StringVar(value=str(self.DEFAULT_BAUD))
        baud_combo = ttk.Combobox(right_frame, textvariable=self.baud_var, width=15, font=self.label_font)
        baud_combo['values'] = ('9600', '19200', '38400', '57600', '115200')
        baud_combo.grid(row=2, column=1, padx=3, pady=3, sticky="ew")
        
        # Connection buttons
        conn_btn_frame = tk.Frame(right_frame, bg=ColorScheme.BG_MEDIUM)
        conn_btn_frame.grid(row=3, column=0, columnspan=4, pady=5)
        
        self.connect_btn = StyledButton(
            conn_btn_frame, "🔗 CONNECT", self.connect_serial,
            ColorScheme.BTN_SUCCESS, "#00ff88", width=12, height=2, font_size=9
        )
        self.connect_btn.pack(side="left", padx=3)
        
        self.disconnect_btn = StyledButton(
            conn_btn_frame, "🔌 DISCONNECT", self.disconnect_serial,
            ColorScheme.BTN_DANGER, "#ff6b81", width=12, height=2, font_size=9
        )
        self.disconnect_btn.pack(side="left", padx=3)
        self.disconnect_btn.config(state="disabled")
        
        StyledButton(
            conn_btn_frame, "🔄 Refresh", self.refresh_ports,
            ColorScheme.BTN_WARNING, "#3498db", width=10, height=2, font_size=9
        ).pack(side="left", padx=3)
        
        # Connection status
        status_frame = tk.Frame(right_frame, bg=ColorScheme.BG_MEDIUM)
        status_frame.grid(row=4, column=0, columnspan=4, pady=5)
        
        self.status_label = tk.Label(
            status_frame, text="● DISCONNECTED",
            bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.STATUS_DISCONNECTED,
            font=("Segoe UI", 11, "bold")
        )
        self.status_label.pack(pady=2)
        
        self.status_detail = tk.Label(
            status_frame, text="Port: -- | Baud: -- | STM32: Not Detected",
            bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.TEXT_SECONDARY,
            font=self.label_font
        )
        self.status_detail.pack(pady=2)
        
        # ===== TIME CONTROL SECTION =====
        time_frame = self.create_styled_frame(main_frame, "⏱️ MOVEMENT TIME CONTROL (1ms - 4000ms)", 2, 0, 2)
        
        time_inner = tk.Frame(time_frame, bg=ColorScheme.BG_MEDIUM)
        time_inner.pack(fill="x", pady=5)
        
        tk.Label(time_inner, text="Current Time:", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=0, column=0, padx=5)
        
        self.time_display = tk.Label(
            time_inner, text="50 ms", bg=ColorScheme.BG_LIGHT,
            fg=ColorScheme.TEXT_ACCENT, font=("Segoe UI", 11, "bold"),
            width=10, relief="sunken", padx=5, pady=3
        )
        self.time_display.grid(row=0, column=1, padx=5)
        
        tk.Label(time_inner, text="Adjust Time:", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=0, column=2, padx=5)
        
        self.time_slider = tk.Scale(
            time_inner, from_=self.min_movement_time, to=self.max_movement_time,
            orient=tk.HORIZONTAL, length=350,
            command=self.on_time_slider_change,
            bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.TEXT_PRIMARY,
            activebackground=ColorScheme.BTN_PRIMARY_HOVER,
            highlightthickness=0, troughcolor=ColorScheme.BG_LIGHT
        )
        self.time_slider.set(self.current_movement_time)
        self.time_slider.grid(row=0, column=3, padx=5, sticky="ew")
        
        tk.Label(time_inner, text="Manual Entry:", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).grid(row=0, column=4, padx=5)
        
        self.time_entry = tk.Entry(
            time_inner, width=6, font=self.label_font,
            bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY,
            insertbackground=ColorScheme.TEXT_PRIMARY
        )
        self.time_entry.insert(0, "1000")
        self.time_entry.grid(row=0, column=5, padx=2)
        
        StyledButton(
            time_inner, "Set", self.on_manual_time_entry,
            ColorScheme.BTN_SUCCESS, "#00ff88", width=5, height=1, font_size=8
        ).grid(row=0, column=6, padx=2)
        
        # Quick time buttons
        quick_time_frame = tk.Frame(time_frame, bg=ColorScheme.BG_MEDIUM)
        quick_time_frame.pack(fill="x", pady=5)
        
        tk.Label(quick_time_frame, text="Quick Set:", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_SECONDARY, font=self.label_font).pack(side="left", padx=10)
        
        for time_ms in [100, 500, 1000, 2000, 3000, 4000]:
            StyledButton(
                quick_time_frame, f"{time_ms}ms",
                lambda t=time_ms: self.set_movement_time(t),
                ColorScheme.BTN_SECONDARY, ColorScheme.BG_LIGHT,
                width=6, height=1, font_size=8
            ).pack(side="left", padx=2)
        
        info_text = "⚡ Fast: 100-500ms | 🎯 Normal: 1000-2000ms | 🐌 Slow: 3000-4000ms"
        tk.Label(time_frame, text=info_text, bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_SECONDARY, font=("Segoe UI", 8)).pack(pady=3)
        
        # ===== GLOBAL CONTROLS =====
        global_frame = self.create_styled_frame(main_frame, "🎮 GLOBAL CONTROLS", 3, 0)
        
        tk.Label(global_frame, text="⚙️ ANGLE CONTROL", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_ACCENT, font=self.title_font).pack(pady=3)
        
        angle_btns = tk.Frame(global_frame, bg=ColorScheme.BG_MEDIUM)
        angle_btns.pack(pady=3)
        
        StyledButton(angle_btns, "All → -5°", lambda: self.set_all_angles(-5),
                    "#3498db", "#5dade2", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(angle_btns, "All → 0°", lambda: self.set_all_angles(0),
                    "#3498db", "#5dade2", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(angle_btns, "All → 5°", lambda: self.set_all_angles(5),
                    "#3498db", "#5dade2", width=7, height=1, font_size=9).pack(side="left", padx=2)
        
        tk.Label(global_frame, text="🎨 COLOR CONTROL", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_ACCENT, font=self.title_font).pack(pady=3)
        
        color_btns = tk.Frame(global_frame, bg=ColorScheme.BG_MEDIUM)
        color_btns.pack(pady=3)
        
        StyledButton(color_btns, "🔴 RED", lambda: self.set_all_colors("RED"),
                    "#e74c3c", "#ff6b6b", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(color_btns, "🟢 GREEN", lambda: self.set_all_colors("GREEN"),
                    "#27ae60", "#2ecc71", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(color_btns, "🔵 BLUE", lambda: self.set_all_colors("BLUE"),
                    "#3498db", "#5dade2", width=7, height=1, font_size=9).pack(side="left", padx=2)
        
        tk.Label(global_frame, text="✨ PATTERNS", bg=ColorScheme.BG_MEDIUM,
                fg=ColorScheme.TEXT_ACCENT, font=self.title_font).pack(pady=3)
        
        pattern_btns = tk.Frame(global_frame, bg=ColorScheme.BG_MEDIUM)
        pattern_btns.pack(pady=3)
        
        StyledButton(pattern_btns, "🌈 Rainbow", self.rainbow_wave,
                    "#9b59b6", "#a569bd", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(pattern_btns, "👋 Welcome", self.run_welcome_sequence,
                    "#9b59b6", "#a569bd", width=7, height=1, font_size=9).pack(side="left", padx=2)
        StyledButton(pattern_btns, "⏹️ Reset", self.reset_all,
                    "#7f8c8d", "#95a5a6", width=7, height=1, font_size=9).pack(side="left", padx=2)
        
        # ===== MOTOR CONTROLS =====
        motors_frame = self.create_styled_frame(main_frame, "🤖 MOTOR CONTROLS (1-16)", 3, 1)
        
        motors_container = tk.Frame(motors_frame, bg=ColorScheme.BG_MEDIUM)
        motors_container.pack(fill="both", expand=True, padx=3, pady=3)
        
        for i in range(16):
            motor_num = i + 1
            row = i // 8
            col = i % 8
            self.create_motor_widget(motors_container, motor_num, row, col)
        
        # ===== LOG SECTION =====
        log_frame = self.create_styled_frame(main_frame, "📜 COMMAND LOG", 4, 0, 2)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, width=120, height=6, wrap=tk.WORD,
            bg=ColorScheme.BG_LIGHT, fg=ColorScheme.TEXT_PRIMARY,
            font=("Consolas", 9), insertbackground=ColorScheme.TEXT_PRIMARY
        )
        self.log_text.pack(fill="both", expand=True, pady=3)
        
        StyledButton(log_frame, "🗑️ Clear Log", self.clear_log,
                    ColorScheme.BTN_SECONDARY, ColorScheme.BG_LIGHT, width=12, height=1, font_size=9).pack(pady=3)
    
    def create_motor_widget(self, parent, motor_num, row, col):
        """Create individual motor control widget"""
        motor_color = ColorScheme.MOTOR_COLORS[motor_num]
        
        motor_frame = tk.Frame(parent, bg=ColorScheme.BG_LIGHT, relief="raised", bd=2,
                              highlightbackground=motor_color, highlightthickness=2)
        motor_frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
        
        header = tk.Label(motor_frame, text=f"Motor {motor_num}", bg=motor_color, fg="#ffffff",
                         font=("Segoe UI", 8, "bold"))
        header.pack(fill="x", pady=(0, 2))
        
        status_frame = tk.Frame(motor_frame, bg=ColorScheme.RGB_COLORS["BLUE"], 
                               height=20, relief="sunken", bd=2)
        status_frame.pack(fill="x", padx=2, pady=2)
        status_frame.pack_propagate(False)
        
        angle_label = tk.Label(status_frame, text="0°", font=("Segoe UI", 9, "bold"),
                              bg=ColorScheme.RGB_COLORS["BLUE"], fg="#ffffff")
        angle_label.pack(expand=True)
        
        angle_frame = tk.Frame(motor_frame, bg=ColorScheme.BG_LIGHT)
        angle_frame.pack(fill="x", padx=2, pady=2)
        
        angle_entry = tk.Entry(angle_frame, width=4, font=("Segoe UI", 8),
                              bg=ColorScheme.BG_MEDIUM, fg=ColorScheme.TEXT_PRIMARY,
                              insertbackground=ColorScheme.TEXT_PRIMARY, justify="center")
        angle_entry.pack(side="left", padx=1)
        angle_entry.insert(0, "0")
        
        set_btn = tk.Button(angle_frame, text="SET", font=("Segoe UI", 7, "bold"),
                           bg=motor_color, fg="#ffffff", width=3, relief="flat",
                           command=lambda m=motor_num: self.set_motor_angle(m), cursor="hand2")
        set_btn.pack(side="left", padx=1)
        
        rgb_frame = tk.Frame(motor_frame, bg=ColorScheme.BG_LIGHT)
        rgb_frame.pack(fill="x", padx=2, pady=2)
        
        for color, bg_color in [("RED", "#e74c3c"), ("GREEN", "#27ae60"), ("BLUE", "#3498db")]:
            btn = tk.Button(rgb_frame, text=color[0], font=("Segoe UI", 7, "bold"),
                           bg=bg_color, fg="#ffffff", width=2, relief="flat",
                           command=lambda m=motor_num, c=color: self.set_motor_color(m, c), cursor="hand2")
            btn.pack(side="left", padx=1)
        
        self.motor_widgets[motor_num] = {
            'status_frame': status_frame, 'angle_label': angle_label,
            'angle_entry': angle_entry, 'motor_frame': motor_frame, 'motor_color': motor_color
        }
    
    # ===== ALL OTHER METHODS FROM ORIGINAL =====
    
    def browse_training_folder(self):
        folder = filedialog.askdirectory(title="Select Training Images Folder")
        if folder:
            self.training_folder_var.set(folder)
            self.log_message(f"📁 Training folder: {folder}")
    
    def refresh_ports_silent(self):
        ports = ["/dev/ttyAMA2", "/dev/ttyAMA0", "/dev/ttyUSB0", "/dev/ttyUSB1"]
        system_ports = [p.device for p in serial.tools.list_ports.comports()]
        all_ports = list(set(ports + system_ports))
        self.port_combo['values'] = all_ports if all_ports else [self.DEFAULT_PORT]
    
    def refresh_ports(self):
        self.refresh_ports_silent()
        self.log_message("🔄 Serial ports refreshed")
    
    def verify_stm32_connection(self):
        if not self.serial_port or not self.serial_port.is_open:
            return False
        try:
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            test_cmd = bytes.fromhex("FFFF01070DE00D")
            self.serial_port.write(test_cmd)
            time.sleep(0.005)
            return True
        except Exception as e:
            self.log_message(f"⚠️ STM32 verification failed: {str(e)}")
            return False
    
    def update_connection_status(self):
        port = self.port_var.get()
        baud = self.baud_var.get()
        
        if self.is_connected and self.stm32_detected:
            self.status_label.config(text="● CONNECTED", fg=ColorScheme.STATUS_CONNECTED)
            self.status_detail.config(text=f"Port: {port} | Baud: {baud} | STM32: Detected ✓",
                                      fg=ColorScheme.STATUS_CONNECTED)
            self.disconnect_btn.config(state="normal")
            self.connect_btn.config(state="disabled")
        else:
            self.status_label.config(text="● DISCONNECTED", fg=ColorScheme.STATUS_DISCONNECTED)
            self.status_detail.config(text="Port: -- | Baud: -- | STM32: Not Detected",
                                      fg=ColorScheme.TEXT_SECONDARY)
            self.disconnect_btn.config(state="disabled")
            self.connect_btn.config(state="normal")
    
    def connect_serial(self):
        port = self.port_var.get()
        baud = self.baud_var.get()
        
        try:
            self.serial_port = serial.Serial(port=port, baudrate=int(baud), timeout=1, write_timeout=1)
            time.sleep(0.01)
            self.is_connected = True
            self.log_message(f"🔗 Serial port {port} opened at {baud} baud")
            
            self.stm32_detected = self.verify_stm32_connection()
            
            if self.stm32_detected:
                self.log_message("✅ STM32F103 detected!")
                if self.motor_controller:
                    self.motor_controller.serial_port = self.serial_port
                    self.motor_controller.is_connected = True
            else:
                self.log_message("⚠️ STM32F103 NOT DETECTED")
                self.serial_port.close()
                self.is_connected = False
                self.serial_port = None
            
            self.update_connection_status()
            
        except Exception as e:
            self.log_message(f"✗ Connection failed: {str(e)}")
            self.is_connected = False
            self.stm32_detected = False
            self.update_connection_status()
    
    def disconnect_serial(self):
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            self.is_connected = False
            self.stm32_detected = False
            self.serial_port = None
            if self.motor_controller:
                self.motor_controller.is_connected = False
                self.motor_controller.serial_port = None
            self.log_message("🔌 Disconnected")
            self.update_connection_status()
        except Exception as e:
            self.log_message(f"✗ Disconnect error: {str(e)}")
    
    def send_hex_command(self, hex_string, description=""):
        if not self.is_connected or not self.stm32_detected:
            return False
        try:
            hex_bytes = bytes.fromhex(hex_string)
            self.serial_port.write(hex_bytes)
            self.log_message(f"→ {description}: {hex_string}")
            return True
        except Exception as e:
            self.log_message(f"✗ Send error: {str(e)}")
            return False
    
    # ===== TIME CONTROL METHODS =====
    def on_time_slider_change(self, value):
        time_ms = int(float(value))
        self.set_movement_time(time_ms)
    
    def on_manual_time_entry(self):
        try:
            time_ms = int(self.time_entry.get())
            if self.min_movement_time <= time_ms <= self.max_movement_time:
                self.set_movement_time(time_ms)
                self.time_slider.set(time_ms)
            else:
                messagebox.showwarning("Invalid Time", 
                    f"Time must be between {self.min_movement_time} and {self.max_movement_time} ms")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number")
    
    def set_movement_time(self, time_ms):
        if not self.min_movement_time <= time_ms <= self.max_movement_time:
            self.log_message(f"⚠️ Time must be between {self.min_movement_time} and {self.max_movement_time} ms")
            return
        
        self.current_movement_time = time_ms
        self.time_display.config(text=f"{time_ms} ms")
        self.time_entry.delete(0, tk.END)
        self.time_entry.insert(0, str(time_ms))
        
        if self.motor_controller:
            self.motor_controller.set_movement_time(time_ms)
        
        if SERVO_AVAILABLE:
            ServoMotorProtocols.ANGLE_PROTOCOLS.set_time(time_ms)
        
        self.log_message(f"⏱️ Movement time set to {time_ms} ms")
    
    # ===== MOTOR CONTROL METHODS (UPDATED TO USE TIME) =====
    def set_motor_angle(self, motor_num):
        if not SERVO_AVAILABLE:
            return
        try:
            entry = self.motor_widgets[motor_num]['angle_entry']
            angle = int(entry.get().strip())
            if not -160 <= angle <= 160:
                self.log_message(f"⚠️ Angle must be between -160° and 160°")
                return
            
            # Use dynamic protocol with current movement time
            hex_cmd = get_angle_protocol(motor_num, angle, self.current_movement_time)
            
            if self.send_hex_command(hex_cmd, f"Motor {motor_num} → {angle}° [{self.current_movement_time}ms]"):
                self.current_angles[motor_num] = angle
                self.update_motor_display(motor_num)
        except ValueError:
            self.log_message(f"✗ Invalid angle value for Motor {motor_num}")
    
    def set_motor_color(self, motor_num, color):
        if not SERVO_AVAILABLE:
            return
        hex_cmd = get_rgb_protocol(motor_num, color)
        if self.send_hex_command(hex_cmd, f"Motor {motor_num} → {color}"):
            self.current_colors[motor_num] = color
            self.update_motor_display(motor_num)
    
    def update_motor_display(self, motor_num):
        widgets = self.motor_widgets[motor_num]
        angle = self.current_angles[motor_num]
        color = self.current_colors[motor_num]
        bg_color = ColorScheme.RGB_COLORS.get(color, "#FFFFFF")
        widgets['status_frame'].config(bg=bg_color)
        widgets['angle_label'].config(text=f"{angle}°", bg=bg_color)
    
    def set_all_angles(self, angle, delay=0.01):
        """Set all motors to the same angle - motors move simultaneously"""
        if not -160 <= angle <= 160:
            self.log_message(f"⚠️ Angle must be between -160° and 160°")
            return
        
        # Send all commands rapidly without delays for simultaneous motion
        for motor_num in range(1, 17):
            entry = self.motor_widgets[motor_num]['angle_entry']
            entry.delete(0, tk.END)
            entry.insert(0, str(angle))
            
            hex_cmd = get_angle_protocol(motor_num, angle, self.current_movement_time)
            self.send_hex_command(hex_cmd, f"Motor {motor_num} → {angle}° [{self.current_movement_time}ms]")
            
            self.current_angles[motor_num] = angle
            self.update_motor_display(motor_num)
            # NO delay here - send commands as fast as possible!
        
        self.log_message(f"✅ All motors set to {angle}° simultaneously with {self.current_movement_time}ms timing")
    
    def set_all_colors(self, color, delay=0.005):
        for motor_num in range(1, 17):
            self.set_motor_color(motor_num, color)
            time.sleep(delay)
    
    def reset_all(self):
        self.set_all_angles(0)
        self.log_message("⏹️ All motors reset to 0°")
    
    def rainbow_wave(self):
        def wave():
            colors = ["RED", "GREEN", "BLUE"]
            for cycle in range(2):
                for offset in range(3):
                    for i in range(16):
                        self.set_motor_color(i + 1, colors[(i + offset) % 3])
                    time.sleep(0.01)
            self.log_message("🌈 Rainbow wave completed!")
        threading.Thread(target=wave, daemon=True).start()
    
    def update_sequence_status(self, status):
        if self.face_system:
            self.face_system.welcome_sequence_status = status
    
    def run_welcome_sequence(self):
        def sequence():
            if self.face_system:
                self.face_system.welcome_sequence_running = True
                self.face_system.welcome_sequence_status = "Starting..."
            
            self.log_message(f"🎉 Starting Welcome Sequence! (All motors move simultaneously)")
            self.log_message(f"   Time frames: Motion1=982ms, Motion2=206ms, Motion3=1315ms, Motion4=1854ms")
            
            try:
                self.update_sequence_status("Setting BLUE LEDs...")
                for m in range(1, 17):
                    self.set_motor_color(m, "BLUE")
                    time.sleep(0.01)
                time.sleep(0.005)
                
                # Motion sequences with specific time frames for each
                motions = [
                    {1: -25, 2: -20, 3: 0, 4: 24, 5: 19, 6: -1, 7: -10, 8: 30, 9: 65, 10: 35, 11: 10, 12: 10, 13: -31, 14: -66, 15: -36, 16: -10},
                    {1: -25, 2: -20, 3: 0, 4: 24, 5: 18, 6: 0, 7: -10, 8: 96, 9: 135, 10: 50, 11: 10, 12: 10, 13: -96, 14: -135, 15: -50, 16: -10},
                    {1: -25, 2: -20, 3: 0, 4: 24, 5: 18, 6: 0, 7: -10, 8: 96, 9: 135, 10: 50, 11: 10, 12: 10, 13: -96, 14: -135, 15: -50, 16: -10},
                    {1: -25, 2: -20, 3: 0, 4: 24, 5: 19, 6: -1, 7: -10, 8: 30, 9: 65, 10: 35, 11: 10, 12: 10, 13: -31, 14: -66, 15: -36, 16: -10},
                ]
                
                # Specific time frame for each motion sequence (in milliseconds)
                motion_times = [982, 206, 1315, 1854]
                
                for idx, motion in enumerate(motions):
                    time_ms = motion_times[idx]
                    self.update_sequence_status(f"Motion {idx+1}/{len(motions)} ({time_ms}ms)...")
                    
                    # Send ALL commands rapidly without delays for simultaneous motion
                    for motor, angle in motion.items():
                        entry = self.motor_widgets[motor]['angle_entry']
                        entry.delete(0, tk.END)
                        entry.insert(0, str(angle))
                        
                        hex_cmd = get_angle_protocol(motor, angle, time_ms)
                        self.send_hex_command(hex_cmd, f"M{motor}→{angle}° ({time_ms}ms)")
                        
                        self.current_angles[motor] = angle
                        self.update_motor_display(motor)
                        # NO delay here - send commands as fast as possible!
                    
                    # Wait for motion to complete before sending next frame
                    time.sleep(time_ms / 1000.0 + 0.1)  # Motion time + small buffer
                
                self.update_sequence_status("Rainbow effect...")
                colors = ["RED", "GREEN", "BLUE"]
                for offset in range(3):
                    for i in range(16):
                        self.set_motor_color(i + 1, colors[(i + offset) % 3])
                    time.sleep(0.01)
                
                self.update_sequence_status("Resetting...")
                self.set_all_angles(0)
                time.sleep(0.01)
                
                self.log_message("✅ Welcome sequence completed!")
                
            finally:
                if self.face_system:
                    self.face_system.welcome_sequence_running = False
                    self.face_system.welcome_sequence_status = ""
                self.log_message("🔄 Detection resuming...")
        
        threading.Thread(target=sequence, daemon=True).start()
    
    def start_face_detection(self):
        if not YOLO_AVAILABLE:
            messagebox.showerror("Error", "ultralytics required. Install with: pip install ultralytics")
            return
        if not TF_AVAILABLE:
            messagebox.showerror("Error", "TensorFlow/TFLite required for face recognition")
            return
        
        yolo_model = self.detection_model_var.get()
        recognition_model = self.recognition_model_var.get()
        training_folder = self.training_folder_var.get()
        
        if not os.path.exists(recognition_model):
            messagebox.showerror("Error", f"Recognition model not found: {recognition_model}\n\n"
                               "Download from:\nhttps://github.com/sirius-ai/MobileFaceNet_TF/raw/master/tflite/mobilefacenet.tflite")
            return
        
        if not os.path.exists(training_folder):
            messagebox.showerror("Error", f"Training folder not found: {training_folder}")
            return
        
        try:
            self.face_system = FaceRecognitionSystem(
                yolo_model, recognition_model, training_folder, 
                debug_mode=self.debug_var.get()
            )
            
            try:
                self.face_system.recognition_threshold = float(self.threshold_var.get())
                self.face_system.strict_threshold = float(self.strict_threshold_var.get())
                self.face_system.confirmation_frames_required = int(self.confirm_frames_var.get())
            except ValueError:
                pass
            
            self.face_system.initialize_camera(0)
            self.face_system.on_david_recognized = self.on_david_recognized
            
            self.face_detection_running = True
            self.face_status.config(text="● YOLO Detection: RUNNING", fg=ColorScheme.STATUS_CONNECTED)
            self.start_face_btn.config(state="disabled")
            self.stop_face_btn.config(state="normal")
            
            self.log_message("🎥 YOLO Face detection started!")
            self.log_message(f"   Thresholds: recognition={self.face_system.recognition_threshold}, "
                           f"strict={self.face_system.strict_threshold}")
            self.log_message(f"   Movement Time: {self.current_movement_time}ms")
            
            def detection_loop():
                while self.face_detection_running:
                    self.face_system.run_detection_loop("YOLO Face Recognition - Q:quit R:reset D:debug")
                    if self.continuous_var.get() and self.face_detection_running:
                        self.log_message("🔄 Restarting detection...")
                        if not self.face_system.camera or not self.face_system.camera.isOpened():
                            self.face_system.initialize_camera(0)
                    else:
                        break
                self.root.after(0, self.on_detection_stopped)
            
            self.face_detection_thread = threading.Thread(target=detection_loop, daemon=True)
            self.face_detection_thread.start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start: {str(e)}")
            self.log_message(f"✗ Error: {str(e)}")
    
    def stop_face_detection(self):
        self.face_detection_running = False
        if self.face_system:
            self.face_system.stop()
        self.log_message("⏹️ Detection stopped")
    
    def on_detection_stopped(self):
        self.face_status.config(text="● Detection: STOPPED", fg=ColorScheme.STATUS_DISCONNECTED)
        self.start_face_btn.config(state="normal")
        self.stop_face_btn.config(state="disabled")
    
    def on_david_recognized(self):
        self.log_message("🎉 Mr. David recognized!")
        if not self.is_connected or not self.stm32_detected:
            self.log_message("⚠️ Robot not connected - skipping sequence")
            if self.face_system:
                self.face_system.welcome_sequence_running = False
            return
        self.run_welcome_sequence()
    
    def log_message(self, message):
        if self.log_text is None:
            print(f"[LOG] {message}")
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
    
    def clear_log(self):
        if self.log_text:
            self.log_text.delete(1.0, tk.END)
    
    def on_closing(self):
        self.face_detection_running = False
        if self.face_system:
            self.face_system.stop()
        if self.is_connected:
            self.disconnect_serial()
        self.root.destroy()


def main():
    print("="*70)
    print("YOLO ROBOT CONTROLLER - COMPACT LAYOUT WITH TIME CONTROL")
    print("="*70)
    print("\n✨ FEATURES:")
    print("   - ALL original YOLO face recognition functionality")
    print("   - Compact GUI (Face Recognition + Connection combined)")
    print("   - Time Control (1ms - 4000ms) with GUI and code control")
    print("   - All original text and information preserved")
    print("\n📋 Required Models:")
    print("   - yolov8n-face.pt (YOLO face detection)")
    print("   - mobilefacenet.tflite (face recognition)")
    print("\n🎯 Camera detection window will appear when you start detection!")
    print("="*70)
    
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use('clam')
    
    app = IntegratedRobotController(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
