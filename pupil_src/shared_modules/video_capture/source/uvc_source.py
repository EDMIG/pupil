'''
(*)~----------------------------------------------------------------------------------
 Pupil - eye tracking platform
 Copyright (C) 2012-2016  Pupil Labs

 Distributed under the terms of the GNU Lesser General Public License (LGPL v3.0).
 License details are in the file license.txt, distributed as part of this software.
----------------------------------------------------------------------------------~(*)
'''

from . import InitialisationError, Base_Source

import uvc
#check versions for our own depedencies as they are fast-changing
assert uvc.__version__ >= '0.7'

from ctypes import c_double
from pyglui import ui
from time import time,sleep
#logging
import logging
logger = logging.getLogger(__name__)

class UVC_Source(Base_Source):
    """
    Camera Capture is a class that encapsualtes uvc.Capture:
     - adds UI elements
     - adds timestamping sanitization fns.

    Attributes:
        uvc_capture (uvc.Capture): UVC backend object
    """
    def __init__(self, g_pool, frame_size, frame_rate, name=None, uid=None, uvc_controls={}, **settings):
        super(UVC_Source, self).__init__(g_pool)
        self.uvc_capture = None
        devices = uvc.device_list()
        devices_by_name = {dev['name']: dev for dev in devices}
        devices_by_uid  = {dev['uid']: dev for dev in devices}

        # name is given. check if list of names
        names = name if type(name) in (list, tuple) else [name]
        if name:
            for name in names:
                if name in devices_by_name:
                    uid_for_name = devices_by_name[name]['uid']
                    if uvc.is_accessible(uid_for_name):
                        self.uvc_capture = uvc.Capture(uid_for_name)
                        break
                    else: logger.warning('UVC source `%s` is not accessible.'%name)
        # uid is given
        elif uid and uid in devices_by_uid:
            if uvc.is_accessible(uid):
                self.uvc_capture = uvc.Capture(uid)
            else: logger.warning('UVC source `%s` is not accessible.'%devices_by_uid[uid]['name'])
        # neither name nore uid are given, take first accessible device
        elif not name and not uid:
            for uid in device_uids:
                if uvc.is_accessible(uid):
                    self.uvc_capture = uvc.Capture(uid)
                    break
        if not self.uvc_capture:
            raise InitialisationError()

        # Set camera defaults. Override with previous settings afterwards

        if 'C930e' in self.uvc_capture.name:
                logger.debug('Timestamp offset for c930 applied: -0.1sec')
                self.ts_offset = -0.1
        else:
            self.ts_offset = 0.0

        #UVC setting quirks:
        controls_dict = dict([(c.display_name,c) for c in self.uvc_capture.controls])
        try:
            controls_dict['Auto Focus'].value = 0
        except KeyError:
            pass

        if ("Pupil Cam1" in self.uvc_capture.name or
            "USB2.0 Camera" in self.uvc_capture.name):

            if ("ID0" in self.uvc_capture.name or
                "ID1" in self.uvc_capture.name):

                self.uvc_capture.bandwidth_factor = 1.3

                try: controls_dict['Auto Exposure Priority'].value = 0
                except KeyError: pass

                try: controls_dict['Auto Exposure Mode'].value = 1
                except KeyError as e: pass

                try:controls_dict['Saturation'].value = 0
                except KeyError: pass

                try: controls_dict['Absolute Exposure Time'].value = 63
                except KeyError: pass

                try: controls_dict['Backlight Compensation'].value = 2
                except KeyError: pass

                try: controls_dict['Gamma'].value = 100
                except KeyError: pass

            else:
                self.uvc_capture.bandwidth_factor = 2.0
                try: controls_dict['Auto Exposure Priority'].value = 1
                except KeyError: pass
        else:
            self.uvc_capture.bandwidth_factor = 3.0
            try: controls_dict['Auto Focus'].value = 0
            except KeyError: pass

        self.frame_size = frame_size
        self.frame_rate = frame_rate
        for c in self.uvc_capture.controls:
            try:
                c.value = uvc_controls[c.display_name]
            except KeyError as e:
                logger.debug('No UVC setting "%s" found from settings.'%c.display_name)

    def get_frame(self):
        frame = self.uvc_capture.get_frame_robust()
        timestamp = self.g_pool.get_now()+self.ts_offset
        timestamp -= self.g_pool.timebase.value
        frame.timestamp = timestamp
        return frame

    @property
    def settings(self):
        settings = super(UVC_Source, self).settings
        settings['name'] = self.uvc_capture.name
        settings['frame_rate'] = self.frame_rate
        settings['frame_size'] = self.frame_size
        settings['uvc_controls'] = {}
        for c in self.uvc_capture.controls:
            settings['uvc_controls'][c.display_name] = c.value
        return settings
    @settings.setter
    def settings(self,settings):
        self.frame_size = settings['frame_size']
        self.frame_rate = settings['frame_rate']
        for c in self.uvc_capture.controls:
            try:
                c.value = settings['uvc_controls'][c.display_name]
            except KeyError as e:
                logger.debug('No UVC setting "%s" found from settings.'%c.display_name)
    @property
    def frame_size(self):
        return self.uvc_capture.frame_size
    @frame_size.setter
    def frame_size(self,new_size):
        self.g_pool.on_frame_size_change(new_size)
        #closest match for size
        sizes = [ abs(r[0]-new_size[0]) for r in self.uvc_capture.frame_sizes ]
        best_size_idx = sizes.index(min(sizes))
        size = self.uvc_capture.frame_sizes[best_size_idx]
        if size != new_size:
            logger.warning("%s resolution capture mode not available. Selected %s."%(new_size,size))
        self.uvc_capture.frame_size = size

    def set_frame_size(self,new_size):
        self.frame_size = new_size

    @property
    def frame_rate(self):
        return self.uvc_capture.frame_rate
    @frame_rate.setter
    def frame_rate(self,new_rate):
        #closest match for rate
        rates = [ abs(r-new_rate) for r in self.uvc_capture.frame_rates ]
        best_rate_idx = rates.index(min(rates))
        rate = self.uvc_capture.frame_rates[best_rate_idx]
        if rate != new_rate:
            logger.warning("%sfps capture mode not available at (%s) on '%s'. Selected %sfps. "%(new_rate,self.uvc_capture.frame_size,self.uvc_capture.name,rate))
        self.uvc_capture.frame_rate = rate

    @property
    def jpeg_support(self):
        return True

    @staticmethod
    def error_class():
        return uvc.StreamError

    def init_gui(self):
        from pyglui import ui
        ui_elements = []
        #lets define some  helper functions:
        def gui_load_defaults():
            for c in self.uvc_capture.controls:
                try:
                    c.value = c.def_val
                except:
                    pass
        def gui_update_from_device():
            for c in self.uvc_capture.controls:
                c.refresh()

        ui_elements.append(ui.Info_Text('%s Controls'%self.uvc_capture.name))
        sensor_control = ui.Growing_Menu(label='Sensor Settings')
        sensor_control.append(ui.Info_Text("Do not change these during calibration or recording!"))
        sensor_control.collapsed=False
        image_processing = ui.Growing_Menu(label='Image Post Processing')
        image_processing.collapsed=True

        sensor_control.append(ui.Selector(
            'frame_size',self,
            setter=self.set_frame_size,
            selection=self.uvc_capture.frame_sizes,
            label='Resolution'
        ))
        sensor_control.append(ui.Selector('frame_rate',self, selection=self.uvc_capture.frame_rates,label='Frame rate' ) )


        for control in self.uvc_capture.controls:
            c = None
            ctl_name = control.display_name

            #now we add controls
            if control.d_type == bool :
                c = ui.Switch('value',control,label=ctl_name, on_val=control.max_val, off_val=control.min_val)
            elif control.d_type == int:
                c = ui.Slider('value',control,label=ctl_name,min=control.min_val,max=control.max_val,step=control.step)
            elif type(control.d_type) == dict:
                selection = [value for name,value in control.d_type.iteritems()]
                labels = [name for name,value in control.d_type.iteritems()]
                c = ui.Selector('value',control, label = ctl_name, selection=selection,labels = labels)
            else:
                pass
            # if control['disabled']:
            #     c.read_only = True
            # if ctl_name == 'Exposure, Auto Priority':
            #     # the controll should always be off. we set it to 0 on init (see above)
            #     c.read_only = True

            if c is not None:
                if control.unit == 'processing_unit':
                    image_processing.append(c)
                else:
                    sensor_control.append(c)

        ui_elements.append(sensor_control)
        if image_processing.elements:
            ui_elements.append(image_processing)
        ui_elements.append(ui.Button("refresh",gui_update_from_device))
        ui_elements.append(ui.Button("load defaults",gui_load_defaults))
        self.g_pool.capture_source_menu.extend(ui_elements)

    def cleanup(self):
        self.uvc_capture = None
