import os
import numpy as np
import tensorflow as tf
from collections import namedtuple
from tqdm import tqdm

from module import generator, discriminator, sce_loss, recon_loss
from util import load_data_list, attr_extract, preprocess_attr, preprocess_image, preprocess_input

class stargan(object):
    def __init__(self,sess,args):
        __data_dir = os.path.join('.','data','celebA')
        __log_dir = os.path.join('.','assets','log')
        __ckpt_dir = os.path.join('.','assets','checkpoint')
        __epoch = 100
        __batch_size = 1
        __image_size = 128
        __image_channel = 3
        __nf= 64
        __n_labels = 10
        __lambda_cls = 1
        __lambda_rec = 10
        __lr = 0.0001
        __beta1 = 0.5
        __continue_train = False
        
        
        self.sess = sess
        self.data_dir = __data_dir
        self.log_dir = __log_dir
        self.ckpt_dir = __ckpt_dir
        self.epoch = __epoch
        self.batch_size = __batch_size
        self.image_size = __image_size
        self.image_channel = __image_channel
        self.nf = __nf
        self.n_labels = __n_labels
        self.lambda_cls = __lambda_cls
        self.lambda_rec = __lambda_rec
        self.lr = __lr
        self.beta1 = __beta1
        self.continue_train = __continue_train
        
        # hyper-parameter for building the module
        OPTIONS = namedtuple('OPTIONS', ['batch_size', 'image_size', 'nf', 'n_labels'])
        self.options = OPTIONS(self.batch_size, self.image_size, self.nf, self.n_labels)
        
        self.build_model()
        self.saver = tf.train.Saver()
        
    def build_model(self):
        # placeholder
        # input_image: A, target_image: B
        self.real_A = tf.placeholder(tf.float32, 
                                           [None, self.image_size, self.image_size, self.image_channel + self.n_labels],
                                           name = 'input_images')
        self.real_B = tf.placeholder(tf.float32, 
                                           [None, self.image_size, self.image_size, self.image_channel + self.n_labels],
                                           name = 'target_images')
        self.fake_B_sample = tf.placeholder(tf.float32,
                                            [None, self.image_size, self.image_size, self.image_channel],
                                            name = 'fake_images_sample')
        
        # generate image
        self.fake_B = generator(self.real_A, self.options, False, name='gen')
        self.fake_A = generator(self.fake_B, self.options, True, name='gen')
        
        # discriminate image
        # src: real or fake, cls: domain classification 
        self.src_real_B, self.cls_real_B = discriminator(self.real_B[:,:,:,:self.image_channel], 
                                                         self.options, False, name='disc')
        self.src_fake_B, self.cls_fake_B = discriminator(self.fake_B_sample, self.options, True, name='disc')
        
        # loss
        ## discriminator loss ##
        ### adversarial loss
        self.d_real_adv_loss = sce_loss(self.src_real_B, tf.ones_like(self.src_real_B))
        self.d_fake_adv_loss = sce_loss(self.src_fake_B, tf.zeros_like(self.src_fake_B))
        ### domain classification loss
        self.d_real_cls_loss = sce_loss(self.cls_real_B, self.real_B[:,:,:,self.image_channel:])
        ### disc loss function
        self.d_loss = self.d_real_adv_loss + self.d_fake_adv_loss + self.lambda_cls * self.d_real_cls_loss
        
        ## generator loss ##
        ### adv loss
        self.g_fake_adv_loss = sce_loss(self.src_fake_B, tf.ones_like(self.src_fake_B))
        ### domain classificatioin loss
        self.g_fake_cls_loss = sce_loss(self.cls_fake_B, self.real_B[:,:,:,self.image_channel:])
        ### reconstruction loss
        self.g_recon_loss = recon_loss(self.real_A, self.fake_A)
        ### gen loss function
        self.g_loss = self.g_fake_adv_loss + self.lambda_cls * self.g_fake_cls_loss + self.lambda_rec * self.g_recon_loss
        
        # trainable variables
        t_vars = tf.trainable_variables()
        self.d_vars = [var for var in t_vars if 'disc' in var.name]
        self.g_vars = [var for var in t_vars if 'gen' in var.name]
#        for var in t_vars: print(var.name)
        
        # optimizer
        self.d_optim = tf.train.AdamOptimizer(self.lr, beta1=self.beta1).minimize(self.d_loss, var_list=self.d_vars)
        self.g_optim = tf.train.AdamOptimizer(self.lr, beta1=self.beta1).minimize(self.g_loss, var_list=self.g_vars)
        
    
    def train(self):
        # summary setting
        self.summary()
        
        # load train data list & load attribute data
        dataA_files = load_data_list(self.data_dir)
        dataB_files = np.copy(dataA_files)
        attr_names, attr_list = attr_extract(self.data_dir)
        
        # variable initialize
        self.sess.run(tf.global_variables_initializer())
        
        # load or not checkpoint
        if self.continue_train and self.checkpoint_load():
            print(" [*] before training, Load SUCCESS ")
        else:
            print(" [!] before training, no need to Load ")
        
        batch_idxs = len(dataA_files) // self.batch_size # 182599
        #train
        for epoch in range(self.epoch):
            np.random.shuffle(dataA_files)
            np.random.shuffle(dataB_files)
            
            for idx in tqdm(range(batch_idxs)):
                # 
                dataA_list = dataA_files[idx * self.batch_size : (idx+1) * self.batch_size]
                dataB_list = dataB_files[idx * self.batch_size : (idx+1) * self.batch_size]
                attrA_list = [attr_list[os.path.basename(val)] for val in dataA_list]
                attrB_list = [attr_list[os.path.basename(val)] for val in dataB_list]
                # get batch images and labels
                attrA, attrB = preprocess_attr(attr_names, attrA_list, attrB_list)
                imgA, imgB = preprocess_image(dataA_list, dataB_list, self.image_size)
                dataA, dataB = preprocess_input(imgA, imgB, attrA, attrB, self.image_size)
                
                # updatae G network
                feed = { self.real_A: dataA, self.real_B: dataB }
                fake_B, _, summary = self.sess.run([self.fake_B, self.g_optim, self.g_sum], 
                                           feed_dict = feed)
                
                #update D network
                feed = { self.real_B: dataB, self.fake_B_sample: fake_B }
                _, summary = self.sess.run([self.d_optim, self.d_sum])
                
                # display(summary) and save
                
            
   
    def summary(self):
        # summary writer
        self.writer = tf.summary.FileWriter(self.log_dir, self.sess.graph)
        
        # session : discriminator
        sum_d_1 = tf.summary.scalar('d_real_adv_loss', self.d_real_adv_loss)
        sum_d_2 = tf.summary.scalar('d_fake_adv_loss', self.d_fake_adv_loss)
        sum_d_3 = tf.summary.scalar('d_real_cls_loss', self.d_real_cls_loss)
        sum_d_4 = tf.summary.scalar('d_loss', self.d_loss)
        self.d_sum = tf.summary.scalar([sum_d_1, sum_d_2, sum_d_3, sum_d_4])
        
        # session : generator
        sum_g_1 = tf.summary.scalar('g_fake_adv_loss', self.g_fake_adv_loss)
        sum_g_2 = tf.summary.scalar('g_fake_cls_loss', self.g_fake_cls_loss)
        sum_g_3 = tf.summary.scalar('g_recon_loss', self.g_recon_loss)
        sum_g_4 = tf.summary.scalar('g_loss', self.g_loss)
        self.g_sum = tf.summary.scalar([sum_g_1, sum_g_2, sum_g_3, sum_g_4])
       
    
    def checkpoint_load(self):
        print(" [*] Reading checkpoint...")
        
        ckpt = tf.train.get_checkpoint_state(self.ckpt_dir)        
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            self.saver.restore(self.sess, os.path.join(self.ckpt_dir, ckpt_name))
            return True
        else:
            return False    