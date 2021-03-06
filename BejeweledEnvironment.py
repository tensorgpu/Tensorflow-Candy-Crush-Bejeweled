#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
File BejeweledEnvironment.py created on 15:39 2017/10/19 

@author: Yichi Xiao
@version: 1.0
"""

import numpy as np
import cv2
import time
import win32api
import win32gui
from PIL import ImageGrab
import win32con

from itertools import product, tee
from collections import deque

from SpriteConvnetModel import SpriteConvnetModel, tf_flags
from ROISelector import selectROI
from img_utils import img_crop_to_array
from Tagging import Tagging
from Environment import Environment

def interpolate(a, b, t):
    if t <= 0:
        return a
    if t >= 1:
        return b
    return a + (b-a) * t


class BejeweledState():
    TYPE_NUM = 11
    def __init__(self, predictions):
        self.prediction = predictions
        assert len(predictions) == 64
        self.state = self.prediction_to_state_one_hot(predictions)

    @staticmethod
    def prediction_to_state_one_hot(prediction):
        a = np.zeros((8,8,BejeweledState.TYPE_NUM))
        for idx, p in enumerate(prediction):
            i, j = int(idx/8), idx%8
            p = int(p)
            if p <= 8:
                a[i,j,p] = 1
            elif 9 <= p and p <= 15:
                a[i,j,p-8] = a[i,j,9] = 1
            else:
                a[i,j,p-15] = a[i,j,10] = 1
        return a # np.eye(BejeweledState.TYPE_NUM)[prediction].reshape(8,8,-1)

    @staticmethod
    def one_hot_state_to_prediction(s):
        r = [0,1,2,3,4,5,6,7,8,8,15]
        p2 = np.tensordot(r, s, axes=([0], [2]))
        return p2.reshape((64,))


class BejeweledAction():
    def __init__(self):
        self.action_space = list(product([0,1,2,3,4,5,6,7], [0,1,2,3,4,5,6], ['H','V']))
        self.action_space = self.action_space + [(0, 0, 'W')]

    def random_action(self):
        return self.action_space[np.random.randint(len(self.action_space))]

    @staticmethod
    def matrix6():
        mat = np.zeros((6, 6, 13, 2*8*7+1), dtype=np.float32)
        for i in range(6):
            for j in range(6):
                # H => 6: (i+{0,1,2},j+{0,1})
                # V => 6: (j+{0,1,2},i+{0,1})
                for idx, (delta_i, delta_j) in enumerate(((0,0), (0,1), (1,0), (1,1), (2,0), (2,1))):
                    x = i + delta_i
                    y = j + delta_j
                    mat[i, j, idx, (x*7+y)*2] = 1
                    x = j + delta_i
                    y = i + delta_j
                    mat[i, j, idx+6, (x*7+y)*2+1] = 1
                mat[i, j, 12, 2*7*8] = 1
        return mat


class BejeweledEnvironment(Environment):    
    def __init__(self, board, ratio=1.25):
        super(BejeweledEnvironment, self).__init__()
        self.ratio = ratio
        self.SPRITE_RATIO = (0.3305, 0.1175, 0.9572, 0.9088)
        self.hwnd = None
        self.game_rect = None
        self.get_hwnd("Bejeweled 3", "MainWindow")
        self.screen_size = self.get_screen_resolution()
        self.force_front_flag = True
        self.recognize_digit = True
        self.action_space = BejeweledAction().action_space
        self._state_queue = deque()
        self.board = board
        self.icon_blank = self.get_icon_data("./icon/blank.png")
        self.icon_0 = self.get_icon_data("./icon/0.png")
        self.icon_1 = self.get_icon_data("./icon/1.png")
        self.icon_2 = self.get_icon_data("./icon/2.png")
        self.icon_3 = self.get_icon_data("./icon/3.png")
        self.icon_4 = self.get_icon_data("./icon/4.png")
        self.icon_5 = self.get_icon_data("./icon/5.png")
        self.icon_6 = self.get_icon_data("./icon/6.png")

        for _ in range(4):
            self._state_queue.append(BejeweledState(np.zeros(64)).state)

        # state store
        self.last_image = None
        self.last_state = None
        self.last_score = 0

        self.state_iterator = self.gen_state()
        self.state_iterator.send(None)

        # others
        self.render_timestamp = time.time()

    def get_icon_data(self, img_path):
        img = cv2.imread(img_path, cv2.IMREAD_COLOR);
        np_image_data = np.asarray(img, dtype=np.float16)
        np_image_data = cv2.normalize(np_image_data.astype('float'), None, 0.0, 1.0, cv2.NORM_MINMAX)
        return np_image_data

    def get_initial_state(self):
        return next(self.state_iterator)

    def reset(self):
        self.last_image = None
        self.last_state = None
        self.last_score = 0

        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.16, 0.88)))
        #time.sleep(0.1)
        ### robust start
        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.57, 0.85)))
        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.57, 0.90)))
        #time.sleep(0.7)
        ### robust end
        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.54, 0.76)))
        #time.sleep(1.8)
        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.20, 0.28)))
        #time.sleep(0.5)
        #self.mouse_click_on_screen(self.game_ratio_to_screen_point((0.54, 0.44)))
        #time.sleep(3)

        # do reset step
        ret = self.get_initial_state()

        return ret

    def step(self, action, wait=0):
        if type(action) != BejeweledAction:
            action = self.action_space[action]
        a, b, c = action
        row1, row2, col1, col2 = 0, 0, 0, 0
        w = False
        if c == 'H':
            row1, row2 = a, a
            col1, col2 = b, b+1
        elif c == 'V':
            col1, col2 = a, a
            row1, row2 = b, b+1
        elif c == 'W':
            w = True
        else:
            print("Invalid Action!")
            return None
        if not w:
            #self.mouse_click_on_sprite(row1, col1)
            #time.sleep(0.05)
            #self.mouse_click_on_sprite(row2, col2)
            swapTuple = []
            swapTuple.append((row1, col1))
            swapTuple.append((row2, col2))
            self.board.performAction(swapTuple);
        else:
            time.sleep(0.5)
        time.sleep(wait)
        # capture next state after wait
        cached_digits = self.last_score
        predictions, digits = next(self.state_iterator)
        self.last_score = digits
        reward = 0
        if cached_digits:
            reward = digits - cached_digits
        if reward < 0:
            reward = 0
        if reward >= 10:
            reward = 10
        #if reward > 0:
        #    print("[GOT REWARD]", int(reward*100))
        if reward == 0:
            reward = -0.1
        # print("Step Action: {}, Reward: {} ({} -> {})".format(action, reward, cached_digits, digits))
        return predictions, reward, False

    def render(self, show=True):
        duration = int(1000*(time.time() - self.render_timestamp))
        zero_img = np.zeros(self.last_image.shape, np.uint8)
        result = Tagging.attach(zero_img, BejeweledState.one_hot_state_to_prediction(self._state_queue[0]))

        cv2.putText(result, '%s ms' % duration, (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 3)
        if show:
            cv2.imshow('Sprites', result)
            cv2.moveWindow('Sprites', 0, 0)
            cv2.waitKey(1)
        self.render_timestamp = time.time()
        return result

    ''' Get current state representation:
        1. Grab Screen
        2. Use SpriteConvnetModel to predict
        3. restructure the prediction
    '''
    def gen_state(self):
        #self.prediction_iterator.send(None)
        #self.digit_iterator.send(None)
        model = SpriteConvnetModel(tf_flags(), False, False)
        model.predict_prepare()
        _last_score = 0
        _last_pred = [0] * 64
        while True:
            #img = self.get_screen_image()
            sprite_feature = self.get_sprite_roi_data()
            digits = self.get_score()
            #digits = 0
            predictions = model.predict(sprite_feature)

            # if score updates, ignore this frame
            if _last_score < digits:
                #print("[SCORE]{} -> {}".format(int(_last_score*100), int(digits*100)))
                _last_score = digits
                _last_pred = predictions
                continue
            else:
                pass

            # if prediction updates, ignore this frame
            if np.count_nonzero(np.array(predictions-_last_pred)) > 0:
                _last_pred = predictions
                continue
            else:
                pass

            predictions = BejeweledState(predictions).state # Package the predictions

            self._state_queue.appendleft(predictions)
            if len(self._state_queue) > 4:
                self._state_queue.pop()
            self.last_state = predictions
            yield predictions, digits

    def get_screen_image(self):
        # ts = time.time()
        img = self.grab_screen(delay=0.01, force_front=self.force_front_flag)
        #cv2.imwrite("thumbnail.png", img)
        # d = int((time.time() - ts) * 1000)
        # print("Grab time:", d, 'ms.')
        return img

    def get_sprite_roi_data(self):        
        # ts = time.time()
        # img = selectROI(image, ratio=self.SPRITE_RATIO)
        # self.last_image = img
        # data = img_crop_to_array(img)
        data = self.get_chips_data()
        # d = int((time.time() - ts) * 1000)
        # print("Predict time:", d, 'ms.')        
        return data

    def get_chips_data(self):
        ''' Divide an image into 8x8 small sprites,
            and then convert them into numpy arrays.
            Shape of returned array: (64, 32, 32, 3)
        '''
        chips = self.board.board
        #sprite_size = 32
        #img = cv2.resize(image, (sprite_size * 8, sprite_size * 8))
        #np_image_data = np.asarray(img, dtype=np.float16)
        #np_image_data = cv2.normalize(np_image_data.astype('float'), None, 0.0, 1.0, cv2.NORM_MINMAX)
        np_data_4d = np.array([]).reshape((0, 32, 32, 3))
        for x in range(8):
            for y in range(8):
                chip = chips[x][y]
                sprite = self.get_sprite(chip)
                np_data_4d = np.concatenate((np_data_4d, sprite[np.newaxis, ...]), axis=0)
        return np.asarray(np_data_4d, dtype=np.float16)

    def get_sprite(self, chip):
        if chip == 0:
            return self.icon_0
        elif chip == 1:
            return self.icon_1
        elif chip == 2:
            return self.icon_2
        elif chip == 3:
            return self.icon_3
        elif chip == 4:
            return self.icon_4
        elif chip == 5:
            return self.icon_5
        elif chip == 6:
            return self.icon_6
        return self.icon_blank

    def get_score(self):
        return self.board.score

    def get_digit(self, image, min_score):
        return 0
        #if self.recognize_digit:
        #    import pyocr
        #    import pyocr.tesseract as tess
        #    import pyocr.builders
        #    from PIL import Image

        #    digit_ratio = (0.1016, 0.1836, 0.2228, 0.2268)
        #    digits = selectROI(image, ratio=digit_ratio, round8=False)
        #    bw_img = digits
        #    cv2.imwrite('digit_sample.jpg', bw_img)
        #    txt = tess.image_to_string(
        #        Image.fromarray(bw_img),
        #        lang='eng',
        #        builder=pyocr.builders.TextBuilder()
        #    )
        #    txt = txt.replace(',','').replace('.','')
        #    if txt.isdigit() and int(txt) >= min_score: # reward should not decrease
        #        score = int(txt) / 100.0
        #    else:
        #        score = min_score
        #    # print("TXT:", txt, 'score:', score , 'last_score:', last_score)
        #    # scale score

        #    return score
        #else:
        #    return 0

    def get_screen_resolution(self):
        width = win32api.GetSystemMetrics(0)
        height = win32api.GetSystemMetrics(1)
        return width, height

    def get_hwnd(self, caption, clazz):
        self.hwnd = win32gui.FindWindow(clazz, caption)
        if not self.hwnd:
            print('window not found!')
        return self.hwnd

    def grab_screen(self, delay=0.25, force_front=False):
        try:
            if force_front:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)  # 强行显示界面后才好截图
                win32gui.SetForegroundWindow(self.hwnd)  # 将窗口提到最前
                self.force_front_flag = False
        except:
            return None
        time.sleep(delay)
        #  裁剪得到全图
        game_rect = win32gui.GetWindowRect(self.hwnd)
        game_rect = tuple(int(self.ratio * x) for x in game_rect)
        self.game_rect = game_rect
        pil_image = ImageGrab.grab(game_rect).convert('RGB')
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_BGR2RGB)
        return image

    def get_cursor_ratio(self):
        cursor_info = win32gui.GetCursorInfo()[2]
        c = (cursor_info[0]*1.25, cursor_info[1]*1.25)
        gr = self.game_rect
        r1 = 1.0 * (c[0] - gr[0]) / (gr[2] - gr[0])
        r2 = 1.0 * (c[1] - gr[1]) / (gr[3] - gr[1])
        return r1, r2

    ''' input: (ratio_w, ratio_h)
        pos_w = game_rect_ws + game_rect_width * ratio_w
        pos_h = game_rect_hs + game_rect_height* ratio_h
    '''
    def game_ratio_to_screen_point(self, cur_ratio):
        gr = self.game_rect
        pos_w = gr[0] * (1-cur_ratio[0]) + gr[2] * cur_ratio[0]
        pos_h = gr[1] * (1-cur_ratio[1]) + gr[3] * cur_ratio[1]
        p1 = int(pos_w/self.ratio)
        p2 = int(pos_h/self.ratio)
        return p1, p2

    def mouse_click_on_sprite(self, row, col):
        r1 = interpolate(self.SPRITE_RATIO[0], self.SPRITE_RATIO[2], (col+0.5)/8)
        r2 = interpolate(self.SPRITE_RATIO[1], self.SPRITE_RATIO[3], (row+0.5)/8)
        pos = self.game_ratio_to_screen_point((r1, r2))
        self.mouse_click_on_screen(pos)

    def mouse_click_on_screen(self, pos):
        win32api.SetCursorPos(pos)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def send_esc(self):
        win32api.keybd_event(27, 0, 0, 0)
        win32api.keybd_event(27, 0, win32con.KEYEVENTF_KEYUP, 0)