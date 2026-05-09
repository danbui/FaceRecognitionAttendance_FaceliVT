# Attendance Recording System Using Deep Face

## 1. Paper Information

- Title: Attendance Recording System Using Deep Face
- Task:
- Model type:
- Year:

## 2. Raw Extracted Text



<!-- Page 1 -->

979-8-3315-3827-9/25/$31.00 ©2025 IEEE
Attendance Recording System Using Deep Face
Detection and Recognition Models

1st Enais Adnan Moses Deli
Department  of Computer Science, College of
Education,University of Kufa
Najaf, Iraq
enaisa.abughoneim@student.uokufa.edu.iq
2nd Hasan Thabit Rashid Kurmasha
Department  of Computer Science, College of Education for
Women,University of Kufa
Najaf, Iraq
hasant.kurmasha@uokufa.edu.iq
Abstract—In this paper, deep neural network called
“Yunet” is used for face detection and the sigmoid-constrained
hypersphere loss called “Sface” is applied for face recognition
to track student attendance in real educational institutions.
Both Yunet and Sface common in using five landmarks for
each face which is a new and effective way to improve the
accuracy, efficiency over attendance management systems
through dynamic and different sizes of deep facial detection
and recognition with high accuracy and faster image
processing. Three datasets are used in; the first one is
designated and generated on educational institutions classes for
academy students and the second one for secondary stage
school were the recorded videos are collected in real standard
and tight criteria on lightning, distances, faces directions, and
the angles of leans while the third one is a generated video for a
popular actors’ images dataset. The designated system is
developed and programed in Python and OpenCV in three
phase’s starting from face detection followed by face
recognition and ending with attendance report collection in
excel file with its metadata. However, the results show that
both Yunet and Sface models can avoid all difficulties and
gotten an excellent accuracy each alone 100% and 98.14%
respectively while the overall attendance recording system has
average accuracy 100% in recording the student status
whether it was present or absence by dealing with tough
conditions. Finally, such this automated system will definitely
eliminate
the
traditional ways  drawbacks for
record
attendance manually.
Keywords—Attendance recording systems, Face detection
and recognition, DNN, CNN, Yunet model, Sface model.
I.
INTRODUCTION
In educational institutions like schools and colleges, an
attendance system is used to automatically record and track
student attendance, by eliminating the need prone manual
signing or roll calling. The system seeks to increase
efficiency and accuracy in the recording of attendance
[1],[2]. Manual attendance recording takes a lot of time and
effort from teachers. It is also prone to error when recording
names, and it may be used to record someone else's
attendance. Thus, the demand need for an automatic
attendance recording system that is effective, dependable,
and
user-friendly
to
track
attendance
in
schools
[3],[4],[5],[6],[7],[8]. This technology analyzes face features
like the mouth, nose, and eyes and turns them into digital
data that may be compared to images kept in a database to
enable identification [9],[10]. Facial recognition is an
excellent approach to identify persons without the need for
manual contact, which helps reduce manipulation in the
attendance system [11]. Yunet model was utilized in recent
works for deep facial detection and however make high
accuracy and quick image processing over  attendance
tracking [12] while Sface model is used to build more
resilient face recognition models [13]. These models was
developed using OpenCV and Python which offers a
comprehensive library for image processing techniques [14].
The other sections of this paper are as following; explain the
most significant studies and techniques pertaining to
attendance recording, and talk about the advantages and
disadvantages of these techniques in the related works
section. The third section shows the general flowchart of the
proposed system approach and all details about applying it.
Forth section presents the instruments and methods
employed and the experimental strategy for design and data
collection as well as present the results and findings
appropriately with explanation using tables and graphs. The
conclusion explains the work contribution and provides a
future work of the key findings to the study. The work
contribution can be summarized as following; first,
designing attendance recording system based on efficient
DNN models called Yunet, Sface. Second, designing and
use two datasets from two educational institutions in real
environment. Finally, excellent results are gotten and
evaluated subjectively and objectively.
II.
RELATED WORKS
Researchers The most popular techniques used for
attendance recording systems with the advantages and
disadvantages can be described as following. FaceNet is a
face recognition model based on deep learning techniques
(DNN). It converts a face image into a digital vector that can
be used for easy or identification by comparing the distances
between the vectors.  FaceNet has proven its performance
on popular databases such as Labelled Faces in the Wild
(LFW) and achieved an accuracy of up to 99.63%. To get
the best results, a lot of data and training are needed.
However, it can be enhanced by better data management and
less reliance on computational resources [15]. Region-based
Convolutional Neural Network (R-CNN) is a sophisticated
CNN-based face detection method. Applied for many huge
datasets like WIDER FACE, FDDB, and IJB-A to provide
fast and accurate results and it has demonstrated excellent
performance on numerous face identification benchmarks.
Nevertheless, it still requires more computer resources than
simpler models. To enhance performance under various
circumstances, a substantial and varied amount of training
data is needed [16], [17]. Retina Face is a new face
detection and recognition technique that uses a multi-level
approach to accurately detect faces and identify landmarks
in images as in Fig. 1. The technique's ability to find faces,
predict 2D facial landmarks, and rebuild 3D faces is typified
by its use of single-shot images. In order to extend various
2025 3rd International Conference on Business Analytics for Technology and Security (ICBATS) | 979-8-3315-3827-9/25/$31.00 ©2025 IEEE | DOI: 10.1109/ICBATS66542.2025.11
DOI: 10.1109/ICBATS66542.2025.11258268



<!-- Page 2 -->

face ranges, the system incorporates features from
hierarchical networks and is built on CNN technology. [18],
[19]. You Only Look Once (YOLO) is a deep Learning model
used to tackle challenging tasks like rapidly and effectively
identifying faces and objects in photos. Datasets like
WIDER FACE and Celeb-Faces have been used to test the
model. Even in huge images, YOLO has demonstrated
strong performance, recognizing faces in 0.027 seconds.
Due to its inability to adjust to fine features, it may have
trouble detecting little or distant faces, but it is resilient in
complicated surroundings and consistently performs well
even in trying circumstances. Significant resources are
needed to provide optimal performance [20],[21],[22].
















Fig. 1. The general steps of Retina Face model.
The new Yunet model is a lightweight and effective
face detection model. Its main goal is to strike a superb
balance between accuracy, speed, and efficiency. It
performs similarly to larger models on datasets like WIDER
FACE and uses less memory and power, making it
appropriate for real-time applications. It is recently used to
solve the problem of heavy and computationally expensive
models that cannot be easily deployed on devices with
limited computing capabilities. It is intended to keep a high
degree of accuracy while lowering latency and parameter
counts. There are three primary components to the model
[12] as in Fig. 2.










Fig. 2. The general flowchart of the Yunet model comonents.

As to Fig. 2 above, the first one is backbone which is
used to extract features from the input image for analysis in
the detection phases. It focuses on small face detection,
which is more difficult than large face detection. The second
one is neck which is a crucial part and incorporates
characteristics from several levels into the backbone in order
to increase the model's ability to detect faces of various
sizes and situations (such as small and large faces). The
final is the head which detect faces using the multi-level
features that Neck has built in. Head concentrates on
delivering precise detection outcomes. The results of
applying the Yunet model as compared to other ones are as
to the following Table 1. Yunet has the fewest parameters
75,856 and is ten times smaller than the majority of other
models in size. When it comes to inference time, Yunet
outperforms other models by many times.

TABLE I.
YUNET COMPARISON WITH OTHER POPULAR TECHNIQUES
[12].

The new Sface model is a loss function used to training
databases with low-quality photos and data noise (like
misaligned or low-resolution images), which is used to build
more resilient face recognition models. it employs sigmoid
curves to rebalance gradients and optimizes intra-class and
inter-class targets on a spherical manifold In order to
enhance training on clean images and lessen the detrimental
impacts of noise. Databases like MS-Celeb-1M, VGGFace2,
and CASIA-Web-Face were used for training. When testing
recognition using one million images, Sface achieved
similar or better performance than other advanced methods,
as shown in Table 2. However, more details can achieved in
[13].
TABLE II.
SFACE VERIFICATION PERFORMANCE WITH OTHER
POPULAR TECHNIQUES BASED ON ON LFW AND YTF DATABASES [13].


Input
size
Methods
Parameters
(ratio)
FLOP
(M)
APhead
Latency
(ms)
320*320

RetinaFace
(359.81x)
0.341
49.1
SCRFD-10g
(55.76x)
0.504
17.3
Yunet
(1.00x)
0.395
2.2
640*640

RetinaFace
-
0.659
232.7
SCRFD-10g
-
0.814
95.0
Yunet
-
0.691
11.3
Origin
size

RetinaFace
-
-
0.847
463.7
SCRFD-10g
-
-
0.885
137.8
Yunet
-
-
0.811
16.3
Methods
Total
Images in Million
LFW
YTF

FaceNet

200 M

99.63
95.10

ArcFace

5.8 M
99.83
98.02
Sface
5.8 M
99.82
98.06

Yunet
1-Backbone
2-Neck
3-Head




<!-- Page 3 -->

III.
THE PROPOSED ATTENDANCE SYSTEM
Several steps will be taken into account to accomplish
the goal of creating an efficient facial attendance recording
system using Yunet and Sface models as mentioned
previously in related work section. Setting and designing
two datasets in educational environment for collagists and
school students as well as using the actor’s dataset will
mention that in section 4. The general flowchart of the
proposed attendance recording system as in Fig. 3.










Fig. 3.  The general flowchart of the proposal attendance recording system
using Yunet and Sface models.
A. The Face Detection Stage
This stage is done using Yunet model after capturing the
class videos, the faces in are discovered. the layers in Yunet
analyze the image to look for distinctive patterns of faces and
then output bounding boxes of the detected faces in the
image as in following Fig. 4 and Fig. 5 respectively.









Fig. 4. The genereal steps of Yunet model. (a)current frame, (b)Yunet
steps, (c) The faces detection by boxes.











Fig. 5. The faces boxes have basic five landmarks features from frame1,
video3, School dataset.
One advantage is that model does not need training as it
is well trained and effective based on its “.onnx feature file”
of face detection and hence; high accuracy in detecting faces
even in environments with poor conditions such lighting or
the face is not ideal, indirect angles, etc.
B. The Face Recognition Stage
There are some things that affect the accuracy of
recognition such as changes in lighting and angles, and the
images may not be good or some student who may look
very similar to others or his face is not clear or the image
has noise which makes the recognition process difficult. The
Sface model avoids that and hence; the students’ faces are
recognized in an excellent way even there are unsuitable
conditions. The recognition process begins, which is
matched the faces detected in the video’ frame with the
faces in the dataset. Here, a certain dynamic thresholds is
used and based on this thresholds, the system considers that
the face in the video matches one of the faces in the
database as Fig. 6 and Fig. 7 respectivly.















Fig. 6. The genereal steps of Sface model. (a)saved DB, (b)detected faces
in current frame by Yunet model, (c) The Sface  steps,(d) the face
from DB and it location in the frame.













Fig. 7. The student face recognition using Sface model and dynamic
thresholds from frame1, video3, School dataset.
C. Attendance Recording Stage
After the face recognition stage, attendance is recorded
for faces that are recognized as present by putting the 1 value
in report excel file, otherwise 0 for absence that are not
recognized faces according to the applied thresholds in the
Video (a set of
frames)
Yunet model
Face detection
Sface model
Face recognition
Database
(images set of
the students’
faces)
Faces
Excel results report
Faces


(a)
(b)                                (c)
(a)
(b)                     (c)                        (d)



<!-- Page 4 -->

matching process. The final result is saved in an Excel sheet
as a daily attendance sheet as Fig. 8.







Fig. 8. The report results of attendance recording system.
IV.
RESULTS AND DISCUSSIONS
The results of applying the Yunet and Sface models and
the proposed attendance recording system for the created
datasets will be show in following sub-sections.
A. New Dataset Creation
As in real world educational environment, three
cameras used (a ready camera, a computer camera, and a
mobile camera) to recorded videos for the 36 volunteers’
students for one minute. Two sessions in different times
were taken in mathematics department of the faculty of
education in Kufa University, after each session their
seating arrangements were then altered, and a video was
taken of them in order to alter the students' looks, positions,
and faces directions and saving that in “University" folder,
the re-arrangements of students’ positions shown in Fig. 9.
Additionally, two sessions in the same scenario were taken
of the secondary school for 40 students and stored as a
dataset in the "School" folder as shown in Fig. 10. Also, a
valuable dataset on internet is used for selected 31 actors’
dataset and 5 images for each actor were saved in a folder
called Actors [23]. There are 100 faces in this folder as in
Fig. 11. The remaining images containing the entire body of
each actor were compiled as video to recognition stage.
P.1
P.5
P.9
P.13
P.11
P.15
P.3
P.7
P.2
P.6
P.10
P.14
P.12
P.16
P.4
P.8
P.3
P.7
P.11
P.15
P.9
P.13
P.1
P.5
P.4
P.8
P.12
P.16
P.10
P.14
P.2
P.6
(a)                                                    (b)
Fig. 9. The students’ positions in classroom. (a) First session, (b) second
session (re-arrange the positions).










Fig. 10. The students faces of  the images in  the used School dataset.














Fig. 11. The actors’ faces as sampled images of the used Actors dataset .
B. The Proposed System Applying
In order to apply the proposed system, a programed
interface was designated and used to execute the
attendance recording system as in the Fig. 12. The user
need to select the video directory from the computer and
then, apply the attendance recording button, the result will
be directly reported to the excel file sheet. The results of
using University dataset, 36 faces were recorded as present
for all students in all videos, which mean all faces were
detected and recognized entirely while in School dataset;
34 faces were recorded as present for all students in all
videos which mean all faces were detected and recognized
entirely as well as in Actor’ dataset, 31 faces were detected
and recognized entirely.

















Fig. 12. The interface for execution of the proposed attendance recording
system.
The following Table 3, Table 4, and Fig. 13 show the
results of detection stage and recognition stage using the
popular evaluation metrics recall, precision, F-score which
counted based on true positive (TP) which is the number of
faces correctly detected and/or recognized as the same face
as in the database of images, true negative (TN) which is the
number of images that are not faces and are correctly
predicted as ‘not a face’ by the applied algorithm, false
positive (FP) refer to the number of images that are not faces,
but are classified as faces, and false negative (FN) refer to
number of images that are faces, but not detected as faces.




<!-- Page 5 -->

TABLE III.
THE AVERAGE ACCURACY OF FACE DETECTION STAGE
USING YUNET MODEL IS 100%. SEE THAT THE MODEL OUTPERFORMS ALL
CHALLENGES IN RECORDING VIDEOS CIRCUMSTANCE SUCH AS DISTANCES,
VIBRATION, OCCLUSIONS, SHOOTING, ETC.



TABLE IV.
THE AVERAGE ACCURACY OF FACE RECOGNITION STAGE
USING SFACE MODEL IS 98.14%.








Fig. 13. The Face detection using Yunet model in red boxes and the
recognition faces using Sface model in green boxes for five students
faces from the database in the first row. Frame5, Video3, School
dataset.
As to above Table 3, all faces in the videos of university
and school dataset, and the actors datasets were detected
under all conditions and the accuracy is excellently100%.
These results improve the power of Yunet model. In Table 4,
because of the absence students as in FNR column, the
results were scored 98.14 %. The results of attendance
recording system in general, there are the present case and
absence case that will be used to measure the accuracy of
system as in Table 5 which achieved  average accuracy
100%.
TABLE V.
THE AVERAGE ACCURACY RESULTS OF THE ATTENDANCE
RECORDING SYSTEM IS 100%.

The result of the proposed attendance recording system
applying for the created two university and school datasets
plus the selected actors dataset can be represented in column
chart as following Fig. 14.














Fig. 14. The average Accuracy results 100% of the proposed attendance
recording system based on the present and/or absance individuals for
all videos of the three used datasets.
The experiments of recording videos has many
challenges that affect the recognition process such as
distances, occlusions, capturing false in the sessions, etc.
therefore, to apply such attendance recording systems there
is a need to detect perfect positions for placing the cameras
and avoiding the vibrations when using hands for mobiles.
Finally, the details for all applied datasets of each video in
respect to durations, lengths, resolutions, sizes, and the
execution times are shown in the following Table 6.






Dataset
student
Videos
Detected
faces
TPR
FNR
Precision
Recall
Accuracy
F1-score
University


V1
V2
V3
School


V1
V2
V3
Actors
V1
Dataset
students
Videos
Recognize
faces
TPR
FNR
Precision
Recall
Accuracy
F1-score
University

V1
0.97
0.97
0.98
V2
0.91
0.91
0.95
V3
School
V1
0.94
0.94
0.96
V2
0.97
0.97
0.98
V3
Actors
V1
Dataset
Total
Students/Actors
Video
Present
Absent
Accuracy

University



V1
1.00
V2
1.00
V3
1.00

School


V1
1.00
V2
1.00
V3
1.00
Actor
V1
1.00




<!-- Page 6 -->

TABLE VI.
THE VIDEOS LENGTH, RESOLUTIONS, SIZES, AND THE
EXECUTION TIMES FOR ALL DATASETS.

V.
CONCLUSION AND FUTURE WORK
This paper propose an attendance recording system
based on face detection and recognition models called
Yunet, Sface respectively which excellently outperforms
traditional techniques in the mechanism of deep face
detection and recognition in low hardware equipment. It is
concluded that Yunet and Sface models have a significant
impact on solving the problems of face detection and
recognition in tough conditions were both are common with
in the property of five landmarks considering. However, the
proposed powerful and effective deep learning system by
three stages for face detection and recognition designed to
handle classrooms attendance in educational environments
with excellent results. Future work is to applying the system
in real-time and executing in different operating system such
android for mobile to facilitates life for academics’ people.

REFERENCES
[1] C.-L. Lin and Y.-H. Huang, ‘The Application of Adaptive Tolerance
and Serialized Facial Feature Extraction to Automatic Attendance
Systems’, Electronics, vol. 11, no. 14, p. 2278, Jul. 2022, doi:
10.3390/electronics11142278.
[2] P. Igiri, ‘ENHANCING CLASS ATTENDANCE WITH AI: A
STUDENT FACE RECOGNITION SYSTEM USING OPENCV’,
vol. 1.
[3] S. M. Bah and F. Ming, ‘An improved face recognition algorithm and
its application in attendance management system’, Array, vol. 5, p.
100014, Mar. 2020, doi: 10.1016/j.array.2019.100014.
[4] D. Sunaryono, J. Siswantoro, and R. Anggoro, ‘An android based
course attendance system using face recognition’, Journal of King
Saud University - Computer and Information Sciences, vol. 33, no. 3,
pp. 304–312, Mar. 2021, doi: 10.1016/j.jksuci.2019.01.006.
[5] T. Srivastava, A. Choudhary, A. K. Srivastava, A. Saxena, P.
Upadhyay,
and
B.
Tech,
‘FACERCLASSROOM:
SMART
ATTENDANCE SYSTEM’, vol. 8, no. 12, 2024.
[6] S. Shrikhande, S. Borse, and S. Bhatlawande, ‘Face Recognition
Based Attendance System’.
[7] H. Yang and X. Han, ‘Face Recognition Attendance System Based on
Real-Time Video Processing’, IEEE Access, vol. 8, pp. 159143–
159150, 2020, doi: 10.1109/ACCESS.2020.3007205.
[8] M. Ali, A. Diwan, and D. Kumar, ‘Attendance System Optimization
through Deep Learning FaceRecognition’, IJCDS, vol. 15, no. 1, pp.
1527–1540, Apr. 2024, doi: 10.12785/ijcds/1501108.
[9] M. Z. Khan, S. Harous, S. U. Hassan, M. U. Ghani Khan, R. Iqbal,
and S. Mumtaz, ‘Deep Unified Model For Face Recognition Based on
Convolution Neural Network and Edge Computing’, IEEE Access,
vol. 7, pp. 72622–72633, 2019, doi: 10.1109/ACCESS.2019.2918275.
[10] P. S. Hegde, ‘Face Recognition based Attendance Management
System’, International Journal of Engineering Research, vol. 9, no.
05.
[11] Feri Susanto, Fauziah, and Andrianingsih, ‘Lecturer Attendance
System using Face Recognition Application an Android-Based’,
CNAHPC, vol. 3, no. 2, pp. 167–173, Jul. 2021, doi:
10.47709/cnahpc.v3i2.981.
[12] W. Wu, H. Peng, and S. Yu, ‘YuNet: A Tiny Millisecond-level Face
Detector’, Mach. Intell. Res., vol. 20, no. 5, pp. 656–665, Oct. 2023,
doi: 10.1007/s11633-023-1423-y.
[13] Zhong, Y., Deng, W., Hu, J., Zhao, D., Li, X., & Wen, D. (2021).
Sface: Sigmoid-constrained hypersphere loss for robust face
recognition. IEEE Transactions on Image Processing, 30, 2587-2598.
[14] A. K. Ali and J. Y. Mustafa, ‘User-Friendly Interface Attendance
System Based on Python Libraries and Deep Learning’, Int. J. Data.
Science.,
vol.
5,
no.
1,
pp.
56–62,
Jun.
2024,
doi:
10.18517/ijods.5.1.56-62.2024.
[15] F. Schroff, D. Kalenichenko, and J. Philbin, ‘FaceNet: A unified
embedding for face recognition and clustering’, in 2015 IEEE
Conference on Computer Vision and Pattern Recognition (CVPR),
Boston, MA, USA: IEEE, Jun. 2015, pp. 815–823. doi:
10.1109/CVPR.2015.7298682.
[16] H. Jiang and E. Learned-Miller, ‘Face Detection with the Faster R-
CNN’, in 2017 12th IEEE International Conference on Automatic
Face & Gesture Recognition (FG 2017), Washington, DC, DC, USA:
IEEE, May 2017, pp. 650–657. doi: 10.1109/FG.2017.82.
[17] W. Wu, Y. Yin, X. Wang, and D. Xu, ‘Face Detection With Different
Scales Based on Faster R-CNN’, IEEE Trans. Cybern., vol. 49, no.
11, pp. 4017–4028, Nov. 2019, doi: 10.1109/TCYB.2018.2859482.
[18] J. Deng, J. Guo, E. Ververas, I. Kotsia, and S. Zafeiriou, ‘RetinaFace:
Single-Shot Multi-Level Face Localisation in the Wild’, in 2020
IEEE/CVF Conference on Computer Vision and Pattern Recognition
(CVPR), Seattle, WA, USA: IEEE, Jun. 2020, pp. 5202–5211. doi:
10.1109/CVPR42600.2020.00525.
[19] J. Deng, J. Guo, Y. Zhou, J. Yu, I. Kotsia, and S. Zafeiriou,
‘RetinaFace: Single-stage Dense Face Localisation in the Wild’, May
04, 2019, arXiv: arXiv:1905.00641. doi: 10.48550/arXiv.1905.00641.
[20] W. Yang and Z. Jiachun, ‘Real-time face detection based on YOLO’,
in 2018 1st IEEE International Conference on Knowledge Innovation
and Invention (ICKII), Jeju: IEEE, Jul. 2018, pp. 221–224. doi:
10.1109/ICKII.2018.8569109.
[21] P. Jiang, D. Ergu, F. Liu, Y. Cai, and B. Ma, ‘A Review of Yolo
Algorithm Developments’, Procedia Computer Science, vol. 199, pp.
1066–1073, 2022, doi: 10.1016/j.procs.2022.01.135.
[22] S. M. M, A. Geroge, A. N, and J. James, ‘Custom Face Recognition
Using YOLO.V3’, in 2021 3rd International Conference on Signal
Processing and Communication (ICPSC), Coimbatore, India: IEEE,
May 2021, pp. 454–458. doi: 10.1109/ICSPC51351.2021.9451684.
[23] Face
Recognition
Dataset,
available
on
internet
in
https://www.kaggle.com/datasets/vasukipatel/face-recognition-
dataset?resource=download.

Dataset
Video
Length
by
second
Width×
Height
Size
Execution
time

University
Video1
1920×1027
8.29MB
156s
Video2
1280×720
10.9MB
184s
Video3
1920×1027
11.2MB
254s

School
Video1
1920×1080
108MB
392s
Video2
1920×1080
80MB
388s
Video3
1:16
720×1280
30.5MB
660s
Actors
Video
1:06
720×1280
11.1MB
532s

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
