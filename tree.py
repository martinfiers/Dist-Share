# -*- coding: utf-8 -*-

import Tkinter as tk
import Tix
import os

FOLDER_SEPARATOR = os.sep

class CheckboxTree(object):
    def __init__(self, root, items={}, height=600, width=800, change_function=None):
        self.odd = True
        self.root = root
        self.height = height
        self.width = width
        self.make_list(items)
        self.change_function = change_function
        self.all_items = self.cl.getselection()


    def make_list(self, items):
        self.cl = Tix.CheckList(self.root, 
                                browsecmd=self.selectItem,
                                command=self.selectItem,
                                width=self.width, 
                                height=self.height,)
        self.cl.hlist.configure(indicatorcmd=self.colapse,
                                selectforeground='black')
        self.cl.pack(fill=Tix.BOTH)
        
        if items:
            self.add_items(items)
        
        self.cl.autosetmode()
        for name in self.cl.getselection():
            self.cl.close(name)
    
    def colapse(self,a):
        if self.odd:
            self.odd = False
            return
        self.odd=True

        mode = self.cl.getmode(a)

        if mode == 'close':
            self.cl.close(a)
        elif mode == 'open':
            self.cl.open(a)
    

    def add_items(self, items, parent=''):

        for item in items:
            replaced_item = item.replace('.','#')
            if parent:
                name = '%s.%s' % (parent,replaced_item)
            else:
                name = replaced_item
            self.cl.hlist.add(name, text=item)
            self.cl.setstatus(name, 'on')

            if items[item]:
                self.add_items(items[item], name)

    def selectItem(self, item):
        status = self.cl.getstatus(item)
        #do the top-bottom propagation
        for i in self.all_items:
            if isinstance(i, tuple):
                if ' '.join(i).startswith(item+'.'):
                    self.cl.setstatus(i, status)
            elif i.startswith(item+'.'):
                self.cl.setstatus(i, status)
        
        #do the bottom-up propagation
        parent = '.'.join(item.split('.')[:-1])
        while status == 'on' and parent and self.cl.getstatus(parent) == 'off':
            self.cl.setstatus(parent, 'on')
            parent = '.'.join(parent.split('.')[:-1])
        
        if self.change_function:
            self.change_function()
    
    def forget(self):
        self.cl.forget()

    def get_checked_items(self, mode='on'):
        items = []
        for item in self.cl.getselection(mode=mode):
            if isinstance(item,str):
                items.append(item.replace('.', FOLDER_SEPARATOR).replace('#','.'))
            elif isinstance(item,tuple):
                items.append(' '.join(item).replace('.', FOLDER_SEPARATOR).replace('#','.'))
        return items
    
    def set_unchecked_items(self, items):
        for item in items:
            item = item.replace('.','#').replace(FOLDER_SEPARATOR,'.')
            self.cl.setstatus(item, 'off')
    
    def set_all_items(self):
        for item in self.all_items:
            self.cl.setstatus(item, 'on')


if __name__ == '__main__':

    """just for test and exemplification"""
    items = {'one':{'A':{},
                    'AAB':False,
                    },
             'two':{'has_more':{'1':None,
                                '2':{},  #Empty node can be either None or {} or [] or False ...
                                },
                     'blah':{},
                    },
            }

    root = Tix.Tk()
    frame = Tix.Frame(root, bg='white')
    tree = CheckboxTree(frame, items)
    frame.pack(fill=Tix.BOTH)
    root.update()
    root.mainloop()

