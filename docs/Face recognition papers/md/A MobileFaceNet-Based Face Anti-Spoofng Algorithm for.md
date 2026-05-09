# A Mobilefacenet-Based Face Anti-Spoofng Algorithm For

## 1. Paper Information

- Title: A Mobilefacenet-Based Face Anti-Spoofng Algorithm For
- Task:
- Model type:
- Year:

## 2. Raw Extracted Text



<!-- Page 1 -->

Citation: Xiao, J.; Wang, W.; Zhang, L.;
Liu, H. A MobileFaceNet-Based Face
Anti-Spoofing Algorithm for
Low-Quality Images. Electronics 2024,
13, 2801. https://doi.org/10.3390/
electronics13142801
Academic Editor: Stefanos Kollias
Received: 1 June 2024
Revised: 30 June 2024
Accepted: 9 July 2024
Published: 16 July 2024
Copyright: © 2024 by the authors.
Licensee MDPI, Basel, Switzerland.
This article is an open access article
distributed
under
the
terms
and
conditions of the Creative Commons
Attribution (CC BY) license (https://
creativecommons.org/licenses/by/
4.0/).
electronics
Article
A MobileFaceNet-Based Face Anti-Spoofing Algorithm for
Low-Quality Images
Jianyu Xiao 1, Wei Wang 2, Lei Zhang 1 and Huanhua Liu 2,*
School of Computer Science and Engineering, Central South University, Changsha 410075, China
School of Information Technology and Management, Hunan University of Finance and Economics,
Changsha 410205, China
*
Correspondence: liuhuanhua@hufe.edu.cn
Abstract: The Face Anti-Spoofing (FAS) methods plays a very important role in ensuring the security
of face recognition systems. The existing FAS methods perform well in short-distance scenarios, e.g.,
phone unlocking, face payment, etc. However, it is still challenging to improve the generalization
of FAS in long-distance scenarios (e.g., surveillance) due to the varying image quality. In order to
address the lack of low-quality images in real scenarios, we build a Low-Quality Face Anti-Spoofing
Dataset (LQFA-D) by using Hikvision’s surveillance cameras. In order to deploy the model on an edge
device with limited computation, we propose a lightweight FAS network based on MobileFaceNet, in
which the Coordinate Attention (CA) attention model is introduced to capture the important spatial
information. Then, we propose a multi-scale FAS framework for low-quality images to explore multi-
scale features, which includes three multi-scale models. The experimental results of the LQFA-D show
that the Average Classification Error Rate (ACER) and detection time of the proposed method are
1.39% and 45 ms per image for the low-quality images, respectively. It demonstrates the effectiveness
of the proposed method in this paper.
Keywords: face anti-spoofing; low-quality images; MobileFaceNet; coordinate attention; model fusion
1. Introduction
With the rapid development of deep learning in computer vision, the accuracy and
efficiency of face recognition technology have been significantly improved, and has been
widely applied in intelligent security, criminal investigations, medical treatment, education,
and other fields [1]. However, there are still many potential risks in the existing face recog-
nition systems that are vulnerable to Presentation Attacks (PAs), ranging from print, replay,
makeup, and 3D masks [2,3]. These spoofing attacks seriously threaten the security and
reliability of face recognition systems, pose safety hazard to people’s property and privacy,
and bring great challenges in public security management. Therefore, both academia and
industry have paid extensive attention to developing Face Anti-Spoofing (FAS, namely,
‘face presentation attack detection’ or ‘face liveness detection’) technology for securing face
recognition systems.
The existing FAS methods can be roughly divided into traditional handcrafted feature-
based methods, hybrid (handcrafted + deep learning), and end-to-end deep learning
methods. Traditional handcrafted feature-based FAS methods exploit human liveness
cues [4–7] and handcrafted features [8–15]. The liveness cue-based methods explore dy-
namic discrimination, e.g., head movement [4], gaze tracking [5], eye-blinking [6], and
remote physiological signals [7]. However, these physiological liveness cues are usually
captured from long-term interactive face videos, which is inconvenient for practical de-
ployment. The other handcrafted-based methods exploit the traditional descriptors (e.g.,
LBP [8], SIFT [9], and SURF [10]), texture [11,12], color distribution [13], and image qual-
ity [14,15] to extract effective spoofing patterns. The traditional handcrafted feature-based
Electronics 2024, 13, 2801. https://doi.org/10.3390/electronics13142801
https://www.mdpi.com/journal/electronics



<!-- Page 2 -->

Electronics 2024, 13, 2801
2 of 14
FAS methods need rich task-aware prior knowledge for design, the generalization ability
of which is limited.
Deep learning and Convolutional Neural Network (CNN) have achieved great success
in many computer vision tasks; however, they suffer from the overfitting problem for
FAS tasks due to the limited amount and diversity of the training data. Therefore, the
hybrid FAS methods (handcraft + deep learning) were proposed [16–20]. There are three
types of hybrid frameworks: extracting deep convolutional features from the handcrafted
features [16,17], extracting handcrafted features from deep convolutional features [18],
and fusing the handcrafted and deep convolutional features for more generic representa-
tion [19]. Meanwhile, the emergence of large-scale public FAS datasets with rich attack
types and recorded sensors together with the rapid development of learning techniques
greatly boosts the end-to-end deep learning-based methods [21–27]. The deep learning
FAS method mainly focuses on optimizing network structures [21–24] and integrating deep
features [25–27] to improve its performance.
The FAS methods have achieved excellent performance in traditional scenarios, e.g.,
phone unlocking, face payment, and access authentication [2], in which the quality of the
face images are high. However, FAS in long-distance scenes (i.e., surveillance), such as
station squares, parks, and self-service supermarkets, has not yet been fully explored. The
major reason is that the resolution of faces is low and contains noise from motion blur,
occlusion, and other bad factors in surveillance scenarios, which results in the traditional
FAS not being able to effectively generalize to faces with varying quality. Recovering the
resolution of faces benefits the extraction of informative spoofing cues [28,29]; however, it
is too hard to restore facial details from face images with unknown degradation processes.
How to reduce the impact of image quality to further improve the generalization of FAS
in surveillance scenes is still challenging. Domain generalization-based FAS methods [30]
address the above problem by exploring adversarial learning to minimize the difference
among source domains. Inspired by the idea of domain generalization, we simulate
surveillance scenarios to build a large-scale face dataset with different qualities to learn
quality-invariant features. Then, we propose a lightweight FAS network to further improve
the generalization by learning quality-invariant features. Specifically, we simulate the
surveillance scenarios to build a large-scale face dataset with different qualities. Then, we
optimize MobileFaceNet by [31] introducing the Coordinate Attention (CA) module [32].
Finally, we train the proposed FAS network on the built dataset.
Our contributions are as follows:
(1)
We build a Low-Quality Face Anti-Spoofing Dataset (LQFA-D), which contains a large
number of low-quality images by simulating surveillance scenarios.
(2)
We propose a lightweight FAS network for low-quality images based on Mobile-
FaceNet [31], in which we introduce the CA module [32] for informative feature
extraction.
(3)
We implement the proposed model and train multi-scale models by using face images
with multi-scales, and we obtained the final detection results by fusing the multi-scale
models. The experimental results show that the proposed FAS method has advantages
in terms of accuracy and efficiency for low-quality face images.
This paper is organized as follows. The related works are illustrated in Section 2. The
LQFA-D is proposed in Section 3. Section 4 presents the FAS method for low-quality images.
The experiments and analysis are provided in Section 5. Section 6 concludes the paper.
2. Related Work
2.1. Face Anti-Spoofing (FAS)
2.1.1. Handcrafted and Hybrid Methods
Traditional handcrafted feature-based FAS methods mainly explore the traditional
descriptors, e.g., LBP [8], SIF [9], and SURF [10], etc. Motivated by that deep learning and
CNNs have achieved great success in many computer vision tasks. Some recent studies
have proposed hybrid frameworks to combine handcrafted features with deep features



<!-- Page 3 -->

Electronics 2024, 13, 2801
3 of 14
for FAS. One of the hybrids extracts handcrafted features from face inputs firstly, and then
employs CNNs for semantic feature extraction. Chen et al. [16] adopted multi-scale color
LBP features as local texture descriptors, then a random forest was cascaded for semantic
representation. Li et al. [17] captured illumination changes using a 1D CNN with inputs of
the intensity difference histograms from reflectance images. The other type is to extract
handcrafted features from deep convolutional features. Shao et al. [18] extracted motion
features using optical flow from the sequential convolutional features. Another hybrid
framework is to fuse the handcrafted and deep convolutional features for a more generic
representation. Sharifi et al. [19] fused the predicted scores from both handcrafted LBP
features and a deep VGG16 model. Li et al. [20] extracted intensity variation features via
a 1D CNN, which were fused with the motion blur features from motion magnified face
videos.
2.1.2. End-to-End Deep Learning-Based Methods
In recent years, deep learning techniques have largely promoted the development of
FAS methods. On the one hand, more and more advanced network structures have been
used in FAS. Yang et al. [21] proposed the first deep learning-based FAS, in which a CNN
was used to extract features being fed into an SVM for classification. Xu et al. [22] used
Long Short-Term Memory (LSTM) and a CNN together to explore sequential information,
which effectively improves its accuracy. Tu et al. [23] used a pre-trained ResNet50 and
transfer learning to further optimize the LSTM-CNN model. Yu et al. [24] designed a new
Central Difference Convolutional Network (CDCN) and proposed the advanced version
CDCN++ by assembling a multi-scale attention fusion module. One the other hand, many
studies have tried to focus on pre-processing and feature fusion strategies to improve the
performance of FAS. Alotaibi et al. [25] considered that the boundary of facial features
should be degraded after nonlinear diffusion in the 2D spoofing faces, which should be
retained in live faces; therefore, they used nonlinear diffusion to process face images and
then used a CNN to extract features. Atoum et al. [26] proposed a two-channel CNN-based
FAS method, which combined local features and depth information. Liu et al. [27] proposed
a CNN-RNN FAS framework which learned the features from the depth map and remote
Photoplethysmography (rPPG) signal.
2.1.3. FAS Methods for Low-Quality Face Images
To improve the generalization of FAS methods in surveillance scenes, in which the
captured images usually have low quality since they offer suffered from low resolution,
motion blur, occlusion, bad weather, and other bad factors. The method [23] attempted
to recover high-resolution faces from low-resolution faces to extract informative spoofing
cues. Aravena et al. [33] discarded some low-quality samples in training to improve the
performance. In [28], an attention-based FAS network with feature augmentation was
proposed for low-quality face images, which consists of the depth-wise separable attention
module and the multi-modal-based feature augmentation module. Fang et al. [29] proposed
a quality-invariant contrastive learning network to alleviate the performance degradation
caused by image quality. In [34], the image quality degradation was regarded as a domain
generalization problem and an end-to-end adversarial domain generalization network
was proposed to improve the generalization of FAS. In [35], a dynamic feature queue and
progressive training strategy were proposed to enhance the generalization ability of the
FAS in long-distance settings.
2.2. Face Anti-Spoofing Dataset
Large-scale FAS databases paly a key role in deep learning-based methods; however,
it is time-consuming and expensive to build large-scale datasets due to the diversity of
spoofing attacks. Ref. [36] proposed the first public FAS dataset, which used a generic
webcam to collect 5105 live face photos and 7509 spoofing face photos in different locations
and illumination conditions. The spoofing attacks in [37] include complete color face



<!-- Page 4 -->

Electronics 2024, 13, 2801
4 of 14
photos, photos with the eyes covered, and videos. [38] used the high-resolution front-facing
cameras of six smartphones to collect images in multiple settings, different light conditions,
and different backgrounds. The spoofing photos were printed by two different printers,
and spoofing videos were presented by two different display devices. [27] collected live
and spoofing face images from 165 individuals, in which the spoofing attacks include two
printing attacks and four video attacks. In the collection process, the changes in terms
of distance, face pose, face expression, and external illumination were considered. [39]
proposed a large-scale FAS dataset which includes three printing attacks, three paper cut
attacks, three video attacks, and one 3D mask attack. It collected 625,537 images from
10,177 individuals in eight scenes. The face images in the existing public datasets were
captured at a short distance, and the image quality of these are very high and contains
plenty of texture details. There is a gap between the captured images in the above datasets
and those captured in long-distance scenarios.
3. Face Anti-Spoofing Dataset of Low-Quality Images
Due to the lack of low-quality face images collected from practical applications, we
built a Face Anti-Spoofing Low-Quality Image (LQFA-D) dataset by simulating surveillance
scenarios, which can be used to train or test learning based models.
3.1. Collection System
The architecture of the LQFA-D collection system is shown in Figure 1. The front end
is equipped with Hikvision’s surveillance cameras DS-2CD3346FWDA3-I, which have a
1/3 progressive scan CMOS sensor and support the fast detection and capture of faces in
motion. The backend part of the LQFA-D collection system is developed with the official
SDK provided by Hikvision. It is implemented with Java8 and deployed in a computer
with Windows 10. After establishing a connection with the camera through the local area
network, the captured face images are transmitted to the backend and saved.
Figure 1. The overall architecture of LQFA-D collection system.
(1)
In order to simulate real application scenarios and obtain large numbers of low-quality
face images, we configured the camera as follows. Set the width and height of the
captured image to be 1.5 times and twice the width of the face, respectively.
(2)
Adjust the speed of target generation and detection sensitivity to the maximum.
(3)
Enable rapid image capturing, set the threshold of capturing to 40 images per second,
set the maximum time of capturing a single image to 1 s, and set the number of
capturing to be unlimited.
3.2. Collection Process
As shown in Figure 2, the camera is hung on the wall about five meters above the
ground, and the subject stands at a horizontal distance about seven meters away from
the camera. At this distance, the face occupies a very small part of the whole monitoring
picture, which makes the captured image of the face low-resolution and fuzzy. In order to
collect images under different conditions, we collected face images in the afternoon with
strong sunlight, in the evening with dim light, and under normal light. For collecting live
face images, the subject faced the camera to reveal the complete face and walked around
freely. For collecting the spoofing face images, the subject held up a spoofing medium (A4



<!-- Page 5 -->

Electronics 2024, 13, 2801
5 of 14
paper or Ipad) to completely cover the face. Several live face images and spoofing face
images of each subject were captured in different scenarios.
7m

Figure 2. The position between the camera and the subject.
3.3. Statistics of LQFA-D
After preprocessing, 21,504 face images (7356 live face images and 14,108 spoofing
face images) were selected for the LQFA-D. Figure 3 shows samples of the LQFA-D, which
include printing attacks and video attacks. The face color photos were printed by a HP
printer, and the videos were presented by an Ipad. The LQFA-D covers different age groups
and genders, people with or without glasses, as well as a variety of illumination conditions
and face poses. As shown in Figure 4a, the LQFA-D contains people over 20 years old,
the proportion of people in the [20, 30), [30, 40), [40, 50), >50 age group is 16%, 37%, 33%
and 14%, respectively. As shown in Figure 4b,c, the ratio of males to females is about 7:3,
and the ratio of people with glasses to people without glasses is roughly 4:6. As shown in
Figure 4d, the number of images in strong light, dim light, and normal light is almost equal.
Limited by the camera performance, shooting distance, and illumination conditions, the
images in the LQFA-D are low-resolution and have varying degrees of noise and are fuzzy,
too bright, or too dark, which meets the requirements of low-quality images.

Live Faces:
Spoofing Faces:
Figure 3. Part of the samples in LQFA-D.



<!-- Page 6 -->

Electronics 2024, 13, 2801
6 of 14
Figure 4. The data distribution of LQFA-D.
4. A Silent Face Anti-Spoofing Method for Low-Quality Images
In practical applications, the computing ability of edge devices such as surveillance
cameras and industrial computers are limited. In order to achieve real-time detection as
much as possible under the premise of ensuring accuracy, we propose a FAS method for
low-quality images based on a high-precision and lightweight model.
4.1. Model Structure
MobileFaceNet [31] is not only a lightweight model—the model size is only 4 MB
and the number of parameters is less than 1 M—but it also achieves an excellent accu-
racy performance. Therefore, we propose the model by employing the key ideas from
MobileFaceNet: (1) Depth-wise separable convolutions were employed instead of the
standard convolution operation, which reduced the size of the parameters. (2) The shortcut
technique was also used to improve feature extraction. The attention mechanism allows
models to focus on important information in data processing, which has been widely used
in various computer vision tasks to improve the efficiency and accuracy. As we know,
Squeeze-and-Excitation (SE) [40], Efficient Channel Attention (ECA) [41], and CA [32] are
three of the most used attention mechanisms in visual tasks. The SE module enhances the
important features by capturing global information, and ECA reduces the computational
complexity of the SE module by generating channel attention through local interaction
information. However, both SE and ECA only focus on the channel attention and ignore
the spatial information. CA combines spatial and channel information by decomposing the
channel attention mechanism into a two-step process to capture long-range dependencies.
The FAS algorithm distinguishes live faces from spoofing faces, in which the spoofing face
(e.g., imaging distortion, borders with attack medium, etc.) often appear in specific regions
of the image. Therefore, we introduced the CA attention module to capture the spatial
attention; moreover, the CA attention module is a lightweight attention mechanism suitable
for lightweight networks.
Figure 5 shows the proposed bottleneck that was modified from the inverted residual
bottleneck of MobileFaceNet by incorporating the CA module into the block (stride 1).
In the block (stride 1), a 1 × 1 convolution layer followed with a PRelu action function
was used to expand the input dimensions to enhance the feature representation. Then, a
3 × 3 depth-wise convolution layer (stride 1) followed with PRelu was used to perform the
convolution, in which each feature channel was processed by one kernel individually. The
depth-wise convolution reduced the parameter scale at the cost of missing the information



<!-- Page 7 -->

Electronics 2024, 13, 2801
7 of 14
integration across the channels. There are two paths for the output feature; one is to
feed into the CA module to estimate the attention weights. The input feature map is first
subjected to global average pooling along the horizontal (X Avg pool) and vertical (Y Avg
pool) directions to generate two feature maps; the two feature maps were concatenated
and fed into a 2D convolution layer to reduce the channels. After the batch normalization,
no-liner action, 2D convolution, and Sigmoid action processes, a C × H × W weight
matrix (attention weights) was obtained and was used to weight the input feature. After
re-weighting the features, a 1 × 1 point-wise convolution kernel followed with a linear
action function was used to fuse the separate features among the different channels. The
fused features and the input were added through a shortcut connection. The block (stride 2)
was kept the same as that of MobileFaceNet, the stride of the 3 × 3 depth-wise convolution
layer was 2, and there was no shortcut connection.
Figure 5. The bottleneck of the proposed model.
Table 1 shows the configuration of the proposed model. The input is a 80 × 80 RGB
face image, the number of bottlenecks (stride 1) is 12, the extracted feature is pooled by the
global depth-wise convolution, the output of the network is a binary classification, and the
loss is binary cross-entropy.



<!-- Page 8 -->

Electronics 2024, 13, 2801
8 of 14
Table 1. The architecture of the proposed model.
Input
Operator
Number of
Repetitions
Number of
Output Channels
Step Size
80 × 80 × 3
Conv 3 × 3
-
40 × 40 × 64
Conv 3 × 3
-
40 × 40 × 64
bottleneck
-
20 × 20 × 64
bottleneck
20 × 20 × 64
bottleneck
-
10 × 10 × 128
bottleneck
10 × 10 × 128
bottleneck
-
5 × 5 × 128
bottleneck
5 × 5 × 128
Conv 1 × 1
-
5 × 5 × 512
Linear GDC 5 × 5
-
1 × 1 × 512
Linear Conv 1 × 1
-
4.2. Framework
To explore the information of the face, background information, and attack medium
border, we proposed a multi-scale model-based detection framework (shown in Figure 6).
Firstly, the face box is detected by the face detection algorithm RetinaFace [42] from the
original/rescaled input image to obtain 1×, 1.2× and 1.5× scale face images. The 1× face
scale image is cropped along the face box from the original input image that mainly contains
the face details. The input image is rescaled by 1.2 and 1.5 times, and from this the 1.2×
and 1.5× face scale images are cropped, which contain the face, background information,
or the attack medium border. Then, the 1×, 1.2× and 1.5× scale face images are resized
to 80 × 80 and fed into the 1×, 1.2× and 1.5× scale models. The configurations of the 1×,
1.2×, and 1.5× scale model are kept the same (shown in Table 1), and are trained by the 1×,
1.2×, and 1.5× face scale images, respectively. The models obtain a two-channel output
from the extracted features, and output the probabilities of being a positive and negative
sample using Softmax. Finally, the proposed method takes a weighted average of the three
outputs to obtain the final results. The proposed multi-scale framework aims to exploit the
complementarity of the multi-scale images, which not only exploits the living analysis from
the face detail information, but also uses the important auxiliary discrimination information
from the no-face region. This effectively solves the problem of detail loss in low-quality
face images and improves the accuracy.
Crop
1× face
scale image
1.2× face
scale image
1.5× face
scale image
1× scale model
1.2× scale model
1.5× scale model
1×2 output
1×2 output
1×2 output
Softmax
Softmax
Softmax
Take a weighted
average
Detect face
Result
Figure 6. The framework of the proposed method.



<!-- Page 9 -->

Electronics 2024, 13, 2801
9 of 14
5. Experimental Results and Analysis
In order to comprehensively evaluate the detection performance of the proposed
method, we conduct comprehensive experiments on the self-built dataset LQFA-D. The
proposed method is compared with CDCN, CDCN++, MobileFaceNet, MobileFaceNet+SE
and MobileFaceNet+CA methods in terms of the detection accuracy. We also count and
analyze the accuracy of the proposed method when facing different people and illumination
conditions. The proposed method is compared with CDCN, CDCN++, MobileFaceNet,
MobileFaceNet+SE, and MobileFaceNet+CA in terms of model size and computation time.
5.1. Setup
The proposed model was implemented with Pytorch 1.2.0 and Python 3.7. All models
were run in a computer with Intel(R) Core(TM) i5-9300HF CPU @ 2.40 GHz, 16 GB RAM,
NVIDIA GeForce GTX 1660ti and Windows 10. We use LQFA-D for model training and
testing. The live faces were labeled as positive samples and spoofing faces were labeled
as negative samples, respectively. The LQFA-D was randomly divided into a training and
testing sub-set at a ratio of 8:2; the training dataset contained 17,200 images and the test
data contains 4304 images. In order to enhance the richness and diversity of the data, we
performed random cropping, rotation, scaling, flipping, color transformation, and other
operations on the input image during training. In the training stage, the model was trained
by an SGD optimizer with momentum. The initial learning rate and weight decay were
1 × 10−2 and 5 × 10−4, respectively. We trained the model with a maximum of 50 epochs
and set the batch size to 256, while the learning rate reduced tenfold every 15 epochs.
We used the Attack Presentation Classification Error Rate (APCER), Normal Presentation
Classification Error Rate (NPCER), and Average Classification Error Rate (ACER) as the
evaluation metrics of the detection accuracy. In addition, the model size was measured
by Floating Point Operations (FLOPs) and the number of parameters. And the detection
efficiency was measured by the average computation time per image.
5.2. Experimental Results
5.2.1. Evaluation of the Proposed Method
Table 2 shows the detection accuracy of CDCN, CDCN++, MobileFaceNet, Mobile-
FaceNet+SE, MobileFaceNet+CA and the proposed method in this work.
Table 2. The comparison results between the proposed method and other methods in detection
accuracy.
Methods
APCER
NPCER
ACER
CDCN
2.93%
2.45%
2.69%
CDCN++
2.93%
2.31%
2.62%
MobileFaceNet
9.15%
8.36%
8.755%
MobileFaceNet+SE
6.78%
7.20%
6.99%
MobileFaceNet+CA
5.97%
5.84%
5.905%
The proposed method
1.41%
1.36%
1.385%
It can be seen that the APCER, NPCER, and ACER of the proposed model are 1.41%,
1.36%, and 1.385%, which are the lowest detection errors among the compared methods.
Specifically, the accuracy of the proposed method is slightly better than that of CDCN
(2.93%, 2.45%, 2.69%) and CDCN++ (2.93%, 2.31%, 2.62%), and much better than that of
MobileFaceNet, MobileFaceNet+SE, and MobileFaceNet+CA. The reason for this is that the
proposed method fuses multi-scale features by the three different scale models, in which
each model is complementary to each other. The fusing framework not only uses the face
details from the face region, but also exploits auxiliary information from the no-face area.
This increases the detection accuracy significantly. Therefore, even if the proposed method
is implemented based on the lightweight model, its performance is better than that of the
single network. In addition, MobileFaceNet+CA is significantly better than MobileFaceNet



<!-- Page 10 -->

Electronics 2024, 13, 2801
10 of 14
and MobileFaceNet+SE in terms of the detection accuracy. This indicates that CA is more
suitable for FAS than SE, which can cause a significant performance improvement to the
proposed model. The detection results are also plotted in Figure 7.

Figure 7. Detection accuracy of the FAS methods.
To comprehensively evaluate the proposed model, Tables 3–6 show the detection
accuracy for different age groups, different genders, people with/without glasses, and
different illuminations, in which TOTAL represents the number of all the samples in this
category. TP represents the positive samples predicted by the model as positive. FP
represents the negative samples predicted by the model as positive. FN represents the
positive samples predicted by the model as negative. And TN represents the negative
samples predicted by the model as negative.
As Table 3 shows, the APCER, NPCER, and ACER of the [20, 30), [30, 40), [40, 50),
and ≥50 age groups are (2.5%, 0, 1.25%), (1.32%, 1.92%, 1.62%), (1.04%, 1.72%, 1.38%), and
(1.80%, 1.28%, 1.54%), respectively. It can be seen that the accuracy gap is small; therefore,
the proposed model is unbiased towards images of people of different ages and maintains
high accuracy. We can observe a similar phenomenon in Tables 4 and 5, and it can be
concluded that the proposed model is unbiased towards images of people of different ages,
different genders, and with/without glasses; meanwhile, it has a high accuracy. It can
be seen from Table 4 that the APCER, NPCER, and ACER of the normal light, too bright,
and too dark conditions are (0.43%, 0, 0.215%), (0.41%, 0.81%, 0.61%), and (3.46%, 3.10%,
3.28%), respectively. The proposed method is easily affected by the illumination condition,
especially the dim light condition (too dark), for which the detection error is much higher
than that of the normal light and too bright conditions. The reason for this is that the texture
details of the face images captured in a dim light environment (too dark) were lost, which
affected the detection accuracy.
Table 3. The detection results of different age groups.
Age
TOTAL
TP
FN
FP
TN
APCER
NPCER
ACER
[20, 30)
2.5%
1.25%
[30, 40)
1.32%
1.92%
1.62%
[40, 50)
1.04%
1.72%
1.38%
≥50
1.80%
1.28%
1.54%



<!-- Page 11 -->

Electronics 2024, 13, 2801
11 of 14
Table 4. The detection results of different genders.
Gender
TOTAL
TP
FN
FP
TN
APCER
NPCER
ACER
Male
1.48%
1.32%
1.40%
Female
1.28%
1.42%
1.35%
Table 5. The detection results of people with or without glasses.
People with or
without Glasses
TOTAL
TP
FN
FP
TN
APCER
NPCER
ACER
With glasses
1.50%
1.04%
1.27%
Without glasses
1.30%
1.70%
1.50%
Table 6. The detection results of different illumination conditions.
Different Lighting
Conditions
TOTAL
TP
FN
FP
TN
APCER
NPCER
ACER
Normal
0.43%
0.215%
Too bright
0.41%
0.81%
0.61%
Too dark
3.46%
3.10%
3.28%
5.2.2. Complexity Analysis
Table 7 shows the model size and detection time of CDCN, CDCN++, MobileFaceNet,
MobileFaceNet+SE, MobileFaceNet+CA, and the proposed method. It can be seen that
the FLOPs of MobileFaceNet+CA is only 0.242 G, the number of parameters is less than
1 M, and the average computation time per image is only 43 ms. The detection time of the
proposed model is significantly less than that of the CDCN and CDCN, nearly equal to
that of MobileFaceNet+SE, and slightly more than that of MobileFaceNet. The proposed
method consists of three models working in parallel; the extra time was mainly spent on
image cropping. The detection times per image are also plotted in Figure 8.
Figure 8. The computation time of the FAS methods.



<!-- Page 12 -->

Electronics 2024, 13, 2801
12 of 14
Table 7. The comparison results between the proposed method and other methods in model size and
detection efficiency.
Methods
FLOPs
The Number of
Parameters
Computation Times
(ms/per Image)
CDCN
10.24 G
2.245 M
CDCN++
10.78 G
2.257 M
MobileFaceNet
0.241 G
0.991 M
MobileFaceNet+SE
0.242 G
1.014 M
MobileFaceNet+CA
0.242 G
0.999 M
The proposed method
0.677 G
2.997 M
As shown in Tables 2 and 7, the model size and detection time of the proposed single
model is slightly worse than that of MobileFaceNet; however, the detection accuracy of
the proposed model has been significantly improved after introducing CA. Therefore, the
proposed method has the best comprehensive performance, of which the accuracy and
time consuming are enough for real applications.
6. Conclusions and Future Work
Due to the lack of low-quality face images from practical applications, we constructed
the Low-Quality Face Anti-Spoofing Dataset (LQFA-D). In order to detect low-quality
images, we proposed a MobileFaceNet-based Face Anti-Spoofing (FAS) network. A Co-
ordinate Attention (CA) model was introduced to further improve the detection accuracy.
We implemented the proposed model and validated it using the self-constructed dataset,
which showed that the proposed model has the lowest Average Classification Error Rate
(ACER) 1.385%. The running time achieved 45 ms per image which is similar to that of the
MobileFaceNet methods and less than that of the CDCN methods. Therefore, the proposed
method displays an accuracy increase and a low complexity when detecting the authen-
ticity of low-quality face images. In subsequent research, we will study more spoofing
attacks and application scenarios to further improve the generalization and robustness of
the proposed method.
Author Contributions: Study conception and design, J.X. and H.L.; data collection, J.X. and L.Z.;
analysis and interpretation of results, J.X., W.W. and H.L.; draft manuscript preparation, J.X. and H.L.
All authors have read and agreed to the published version of the manuscript.
Funding: This work was supported by the Natural Science Foundation of Hunan Province (Grant No.
2022JJ30002, Grant No. 2024JJ7076), Special Funds for High-Tech Industry Technology Innovation
Leading Plan of Hunan (Grant No. 2022GK4009), Scientific Research Project of Hunan Provincial
Department of Education (Grant No. 21B0836), and Research Foundation of Education Bureau of
Hunan Province (Grant No. 23B0896).
Institutional Review Board Statement: The study was conducted in accordance with the Declaration
of Helsinki, and approved by the Institutional Review Board of Hunan University of Finance and
Economics (No. 2022001, 28 August 2022).
Informed Consent Statement: Informed consent was obtained from all subjects involved in the
study.
Data Availability Statement: The data that support the findings of this study are available from the
corresponding author upon reasonable request.
Conflicts of Interest: The authors declare no conflicts of interest.
References
1.
Zhang, M.; Zeng, K.; Wang, J. A survey on face anti-spoofing algorithms. J. Inf. Hiding Priv. Prot. 2020, 2, 21. [CrossRef]
2.
Yu, Z.; Qin, Y.; Li, X.; Zhao, C.; Lei, Z.; Zhao, G. Deep learning for face anti-spoofing: A survey. IEEE Trans. Pattern Anal. Mach.
Intell. 2022, 45, 5609–5631. [CrossRef] [PubMed]



<!-- Page 13 -->

Electronics 2024, 13, 2801
13 of 14
3.
Ramachandra, R.; Busch, C. Presentation attack detection methods for face recognition systems: A comprehensive survey. ACM
Comput. Surv. (CSUR) 2017, 50, 1–37. [CrossRef]
4.
Bao, W.; Li, H.; Li, N.; Jiang, W. A liveness detection method for face recognition based on optical flow field. In Proceedings of the
2009 International Conference on Image Analysis and Signal Processing, Linhai, China, 11–12 April 2009; pp. 233–236.
5.
Ali, A.; Deravi, F.; Hoque, S. Liveness detection using gaze collinearity. In Proceedings of the 2012 Third International Conference
on Emerging Security Technologies, Lisbon, Portugal, 5–7 September 2012; pp. 62–65.
6.
Li, J.-W. Eye blink detection based on multiple Gabor response waves. In Proceedings of the 2008 International Conference on
Machine Learning and Cybernetics, Kunming, China, 12–15 July 2008; pp. 2852–2856.
7.
Yu, Z.; Peng, W.; Li, X.; Hong, X.; Zhao, G. Remote heart rate measurement from highly compressed facial videos: An end-toend
deep learning solution with video enhancement. In Proceedings of the IEEE/CVF International Conference on Computer Vision,
Seoul, Republic of Korea, 27 October–2 November 2019; pp. 151–160.
8.
Boulkenafet, Z.; Komulainen, J.; Hadid, A. Face anti-spoofing based on color texture analysis. In Proceedings of the 2015 IEEE
International Conference on Image Processing, Quebec City, QC, Canada, 27–30 September 2015; pp. 2636–2640.
9.
Patel, K.; Han, H.; Jain, A.K. Secure face unlock: Spoof detection on smartphones. IEEE Trans. Inf. Forensics Secur. 2016, 11,
2268–2283. [CrossRef]
10.
Boulkenafet, Z.; Komulainen, J.; Hadid, A. Face antispoofing using speeded-up robust features and fisher vector encoding. IEEE
Signal Process. Lett. 2017, 24, 141–145.
11.
Määttä, J.; Hadid, A.; Pietikäinen, M. Face spoofing detection from single images using micro-texture analysis. In Proceedings of
the 2011 International Joint Conference on Biometrics (IJCB), Washington, DC, USA, 11–13 October 2011; pp. 1–7.
12.
De Freitas Pereira, T.; Komulainen, J.; Anjos, A.; De Martino, J.M.; Hadid, A.; Pietikäinen, M.; Marcel, S. Face liveness detection
using dynamic texture. EURASIP J. Image Video Process. 2014, 2014, 2. [CrossRef]
13.
Boulkenafet, Z.; Komulainen, J.; Hadid, A. Face spoofing detection using colour texture analysis. IEEE Trans. Inf. Forensics Secur.
2016, 11, 1818–1830. [CrossRef]
14.
Galbally, J.; Marcel, S.; Fierrez, J. Image quality assessment for fake biometric detection: Application to iris, fingerprint, and face
recognition. IEEE Trans. Image Process. 2013, 23, 710–724. [CrossRef] [PubMed]
15.
Wen, D.; Han, H.; Jain, A.K. Face spoof detection with image distortion analysis. IEEE Trans. Inf. Forensics Secur. 2015, 10, 746–761.
[CrossRef]
16.
Cai, R.; Chen, C. Learning deep forest with multi-scale local binary pattern features for face anti-spoofing.
arXiv 2019,
arXiv:1910.03850.
17.
Li, L.; Xia, Z.; Jiang, X.; Ma, Y.; Roli, F.; Feng, X. 3D face mask presentation attack detection based on intrinsic image analysis. IET
Biom. 2020, 9, 100–108. [CrossRef]
18.
Shao, R.; Lan, X.; Yuen, P.C. Joint discriminative learning of deep dynamic textures for 3D mask face anti-spoofing. IEEE Trans.
Inf. Forensics Secur. 2019, 14, 923–938. [CrossRef]
19.
Sharifi, O. Score-level-based face anti-spoofing system using handcrafted and deep learned characteristics. Int. J. Image Graph.
Signal Process. 2019, 10, 15–20. [CrossRef]
20.
Li, L.; Xia, Z.; Hadid, A.; Jiang, X.; Zhang, H.; Feng, X. Replayed video attack detection based on motion blur analysis. IEEE Trans.
Inf. Forensics Secur. 2019, 14, 2246–2261. [CrossRef]
21.
Yang, J.; Lei, Z.; Li, S.Z. Learn convolutional neural network for face anti-spoofing. arXiv 2014, arXiv:1408.5601.
22.
Xu, Z.; Li, S.; Deng, W. Learning temporal features using LSTM-CNN architecture for face anti-spoofing. In Proceedings of the
2015 3rd IAPR Asian Conference on Pattern Recognition (ACPR), Kuala Lumpur, Malaysia, 3–6 November 2015; pp. 141–145.
23.
Tu, X.; Fang, Y. Ultra-deep neural network for face anti-spoofing. In Proceedings of the International Conference on Neural
Information Processing, Guangzhou, China, 14–18 November 2017; Springer: Cham, Switzerland, 2017; pp. 686–695.
24.
Yu, Z.; Zhao, C.; Wang, Z.; Qin, Y.; Su, Z.; Li, X.; Zhou, F.; Zhao, G. Searching central difference convolutional networks for face
anti-spoofing. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, Seattle, WA, USA,
13–19 June 2020; pp. 5295–5305.
25.
Alotaibi, A.; Mahmood, A. Deep face liveness detection based on nonlinear diffusion using convolution neural network. Signal
Image Video Process. 2017, 11, 713–720. [CrossRef]
26.
Atoum, Y.; Liu, Y.; Jourabloo, A.; Liu, X. Face anti-spoofing using patch and depth-based CNNs. In Proceedings of the 2017 IEEE
International Joint Conference on Biometrics (IJCB), Denver, CO, USA, 1–4 October 2017; pp. 319–328.
27.
Liu, Y.; Jourabloo, A.; Liu, X. Learning deep models for face anti-spoofing: Binary or auxiliary supervision. In Proceedings of the
IEEE Conference on Computer Vision and Pattern Recognition, Salt Lake City, UT, USA, 18–22 June 2018; pp. 389–398.
28.
Chen, X.; Xu, S.; Ji, Q.; Cao, S. A dataset and benchmark towards multi-modal face antispoofing under surveillance scenarios.
IEEE Access 2021, 9, 28140–28155. [CrossRef]
29.
Fang, H.; Liu, A.; Wan, J.; Escalera, S.; Zhao, C.; Zhang, X.; Li, S.Z.; Lei, Z. Surveillance face anti-spoofing. arXiv 2023,
arXiv:2301.00975. [CrossRef]
30.
Wang, Z.; Wang, Z.; Yu, Z.; Deng, W.; Li, J.; Gao, T.; Wang, Z. Domain generalization via shuffled style assembly for face
anti-spoofing. In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, New Orleans, LA, USA,
18–24 June 2022; pp. 4123–4133.



<!-- Page 14 -->

Electronics 2024, 13, 2801
14 of 14
31.
Chen, S.; Liu, Y.; Gao, X.; Han, Z. Mobilefacenets: Efficient cnns for accurate real-time face verification on mobile devices. In
Proceedings of the Biometric Recognition: 13th Chinese Conference, CCBR 2018, Urumqi, China, 11–12 August 2018; Proceedings
13. Springer International Publishing: Berlin/Heidelberg, Germany, 2018; pp. 428–438.
32.
Hou, Q.; Zhou, D.; Feng, J. Coordinate attention for efficient mobile network design. In Proceedings of the IEEE/CVF Conference
on Computer Vision and Pattern Recognition, Nashville, TN, USA, 20–25 June 2021; pp. 13713–13722.
33.
Aravena, C.; Pasmino, D.; Tapia, J.E.; Busch, C. Impact of face image quality estimation on presentation attack detection. arXiv
2022, arXiv:2209.15489.
34.
Liu, Y.; Xu, Y.; Zou, Z.; Wang, Z.; Zhang, B.; Wu, L.; Guo, Z.; He, Z. Adversarial Domain Generalization for Surveillance Face
Anti-Spoofing. In Proceedings of the 2023 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops
(CVPRW), Vancouver, BC, Canada, 17–24 June 2023; pp. 6352–6360. [CrossRef]
35.
Wang, K.; Huang, M.; Zhang, G.; Yue, H.; Zhang, G.; Qiao, Y. Dynamic Feature Queue for Surveillance Face Anti-spoofing via
Progressive Training. In Proceedings of the 2023 IEEE/CVF Conference on Computer Vision and Pattern Recognition Workshops
(CVPRW), Vancouver, BC, Canada, 17–24 June 2023; pp. 6372–6379. [CrossRef]
36.
Tan, X.; Li, Y.; Liu, J.; Jiang, L. Face Liveness Detection from a Single Image with Sparse Low Rank Bilinear Discriminative Model.
In Proceedings of the Computer Vision–ECCV 2010: 11th European Conference on Computer Vision, Heraklion, Crete, Greece,
5–11 September 2010; Volume 6316, pp. 504–517.
37.
Zhang, Z.; Yan, J.; Liu, S.; Lei, Z.; Yi, D.; Li, S.Z. A face antispoofing database with diverse attacks. In Proceedings of the 2012 5th
IAPR International Conference on Biometrics (ICB), New Delhi, India, 29 March–1 April 2012; pp. 26–31.
38.
Boulkenafet, Z.; Komulainen, J.; Li, L.; Feng, X.; Hadid, A. OULU-NPU: A mobile face presentation attack database with
real-world variations. In Proceedings of the 2017 12th IEEE International Conference on Automatic Face & Gesture Recognition
(FG 2017), Washington, DC, USA, 30 May–3 June 2017; pp. 612–618.
39.
Zhang, Y.; Yin, Z.F.; Li, Y.; Yin, G.; Yan, J.; Shao, J.; Liu, Z. Celeba-spoof: Large-scale face anti-spoofing dataset with rich
annotations. In Proceedings of the Computer Vision–ECCV 2020, 16th European Conference, Glasgow, UK, 23–28 August 2020;
Proceedings, Part XII 16; Springer International Publishing: Berlin/Heidelberg, Germany, 2020; pp. 70–85.
40.
Hu, J.; Shen, L.; Sun, G. Squeeze-and-excitation networks. In Proceedings of the IEEE Conference on Computer Vision and Pattern
Recognition, Salt Lake City, UT, USA, 18–22 June 2018; pp. 7132–7141.
41.
Wang, Q.; Wu, B.; Zhu, P.; Li, P.; Zuo, W.; Hu, Q. ECA-Net: Efficient channel attention for deep convolutional neural net-works.
In Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), Seattle, WA, USA, 13–19 June
2020. [CrossRef]
42.
Deng, J.; Guo, J.; Ververas, E.; Kotsia, I.; Zafeiriou, S. Retinaface: Single-shot multi-level face localisation in the wild. In
Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition, Seattle, WA, USA, 13–19 June 2020;
pp. 5203–5212.
Disclaimer/Publisher’s Note: The statements, opinions and data contained in all publications are solely those of the individual
author(s) and contributor(s) and not of MDPI and/or the editor(s). MDPI and/or the editor(s) disclaim responsibility for any injury to
people or property resulting from any ideas, methods, instructions or products referred to in the content.

## 3. Notes

### Problem

### Core Idea

### Architecture

### Dataset

### Metrics

### Strengths

### Weaknesses

### Relevance to Our Pipeline

### Implementation Notes

### Key Takeaways
