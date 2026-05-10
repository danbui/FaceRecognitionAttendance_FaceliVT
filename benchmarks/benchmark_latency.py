"""
Benchmark Latency – Shared pipeline + so sánh Embedding & KNN giữa SFace vs FaceLiVT.

Detection, BestFrame, StateCheck, DB Save: chạy 1 lần (chung).
Embedding + KNN Matching: chạy riêng cho mỗi backend.

  python benchmarks/benchmark_latency.py --folder dataset_clean
  python benchmarks/benchmark_latency.py --folder dataset_clean --max 500
"""
import sys, time, csv, argparse, platform
from pathlib import Path
from datetime import datetime
import cv2, numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.face_detector import FaceDetector
from app.best_frame_selector import BestFrameSelector
from app.config import SFACE_MODEL, FACELIVT_MODEL

ARCFACE_DST = np.array([[38.2946,51.6963],[73.5318,51.5014],[56.0252,71.7366],[41.5493,92.3655],[70.7299,92.2041]], dtype=np.float32)
IMG_EXTS = {".jpg",".jpeg",".png",".bmp",".webp"}

# ── Embedders ──
def align_face(frame, det, size=112):
    try:
        lm = det[4:14].reshape((5,2)); dst = ARCFACE_DST*(float(size)/112.0)
        M,_ = cv2.estimateAffinePartial2D(lm, dst)
        if M is None: M = cv2.getAffineTransform(lm[:3], dst[:3])
        return cv2.warpAffine(frame, M, (size,size), borderValue=0.0)
    except: pass
    x,y,w,h = det[:4].astype(int)
    crop = frame[max(0,y):min(frame.shape[0],y+h), max(0,x):min(frame.shape[1],x+w)]
    return cv2.resize(crop,(size,size)) if crop.size>0 else None

class SFaceWrap:
    name="SFace"
    def __init__(self):
        try:
            buf=np.fromfile(str(SFACE_MODEL),dtype=np.uint8)
            self.rec=cv2.FaceRecognizerSF.create(framework="onnx",bufferModel=buf,bufferConfig=np.array([],dtype=np.uint8))
        except TypeError:
            self.rec=cv2.FaceRecognizerSF.create(str(SFACE_MODEL),"")
        self.embed_dim=128
    def get_embedding(self,frame,det):
        a=self.rec.alignCrop(frame,det); f=self.rec.feature(a).flatten(); n=np.linalg.norm(f)
        return (f/n if n>1e-8 else f).reshape(1,-1)

class FaceLiVTWrap:
    name="FaceLiVT"
    def __init__(self):
        import onnxruntime as ort
        self.sess=ort.InferenceSession(str(FACELIVT_MODEL),providers=['CPUExecutionProvider'])
        self.inp=self.sess.get_inputs()[0].name
        dummy=np.random.randn(1,3,112,112).astype(np.float32)
        self.embed_dim=self.sess.run(None,{self.inp:dummy})[0].flatten().shape[0]
    def get_embedding(self,frame,det):
        face=align_face(frame,det)
        if face is None: return np.zeros((1,self.embed_dim),dtype=np.float32)
        rgb=cv2.cvtColor(face,cv2.COLOR_BGR2RGB)
        blob=(rgb.astype(np.float32)-127.5)/127.5
        blob=np.transpose(blob,(2,0,1))[np.newaxis,...]
        out=self.sess.run(None,{self.inp:blob})[0]; emb=out.flatten(); n=np.linalg.norm(emb)
        return ((emb/n) if n>1e-8 else emb).reshape(1,-1)

# ── Gallery & KNN ──
def enroll_gallery(images, detector, embedder):
    embs,ids=[],[]
    for p in images:
        person=Path(p).parent.name
        try:
            buf=np.fromfile(str(p),dtype=np.uint8); img=cv2.imdecode(buf,cv2.IMREAD_COLOR)
            if img is None: continue
            box,raw=detector.detect_largest_with_raw(img)
            if raw is None: continue
            embs.append(embedder.get_embedding(img,raw).flatten()); ids.append(person)
        except: pass
    if not embs: return np.zeros((0,embedder.embed_dim),dtype=np.float32),[]
    return np.array(embs,dtype=np.float32), ids

def knn_match(q, matrix, ids, k=5, thr=0.3):
    if matrix.shape[0]==0: return None
    qf=q.flatten().astype(np.float32); n=np.linalg.norm(qf)
    if n<1e-8: return None
    qf/=n; scores=matrix@qf; K=min(k,len(scores)); top=np.argsort(scores)[-K:][::-1]
    votes={}
    for i in top:
        s=float(scores[i])
        if s<thr: continue
        votes[ids[i]]=votes.get(ids[i],0)+1
    if not votes: return None
    return max(votes,key=votes.get)

# ── Helpers ──
def collect_images(folder, mx=0):
    imgs=sorted(f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXTS)
    return imgs[:mx] if mx>0 else imgs

def load_image(p):
    buf=np.fromfile(str(p),dtype=np.uint8); img=cv2.imdecode(buf,cv2.IMREAD_COLOR)
    if img is None: raise ValueError(p)
    return img

def get_sys_info():
    i={"platform":platform.platform(),"machine":platform.machine(),"python":platform.python_version(),
       "opencv":cv2.__version__,"numpy":np.__version__}
    try: import onnxruntime as ort; i["onnxruntime"]=ort.__version__
    except: i["onnxruntime"]="N/A"
    return i

def stats(vals):
    if not vals: return {"mean":0,"med":0,"p95":0,"min":0,"max":0,"std":0,"n":0}
    a=np.array(vals)
    return {"mean":float(np.mean(a)),"med":float(np.median(a)),"p95":float(np.percentile(a,95)),
            "min":float(np.min(a)),"max":float(np.max(a)),"std":float(np.std(a)),"n":len(a)}

# ── Benchmark core ──
def benchmark_all(images, detector, selector, sface, facelivt, sg, si, fg, fi, warmup=3):
    # Warmup
    for p in images[:warmup]:
        try:
            fr=load_image(p); _,raw=detector.detect_largest_with_raw(fr)
            if raw is not None:
                sface.get_embedding(fr,raw); facelivt.get_embedding(fr,raw)
        except: pass

    # Per-step accumulators
    det_t,bf_t=[],[]                          # shared
    emb_s,emb_f=[],[]                         # per-backend embedding
    knn_s,knn_f=[],[]                         # per-backend matching
    state_t,db_t=[],[]                        # shared
    total_s,total_f=[],[]                     # total per-backend
    faces,errors,total=0,0,len(images)

    for idx,p in enumerate(images):
        try:
            fr=load_image(p)
        except:
            errors+=1; continue

        # 1. Detection (SHARED)
        t=time.perf_counter()
        box,raw=detector.detect_largest_with_raw(fr)
        dt_det=(time.perf_counter()-t)*1000
        det_t.append(dt_det)

        if raw is None:
            continue
        faces+=1

        # 2. Best Frame (SHARED)
        t=time.perf_counter()
        selector.reset(); selector.update(fr.copy(),box,raw[4:14],raw)
        bf,br,_=selector.get_best()
        if bf is None: bf,br=fr,raw
        dt_bf=(time.perf_counter()-t)*1000
        bf_t.append(dt_bf)

        # 3. Embedding (TÁCH)
        t=time.perf_counter()
        emb_sface=sface.get_embedding(bf,br)
        dt_es=(time.perf_counter()-t)*1000
        emb_s.append(dt_es)

        t=time.perf_counter()
        emb_flivt=facelivt.get_embedding(bf,br)
        dt_ef=(time.perf_counter()-t)*1000
        emb_f.append(dt_ef)

        # 4. KNN Matching (TÁCH — gallery riêng)
        t=time.perf_counter()
        ms=knn_match(emb_sface,sg,si)
        dt_ks=(time.perf_counter()-t)*1000
        knn_s.append(dt_ks)

        t=time.perf_counter()
        mf=knn_match(emb_flivt,fg,fi)
        dt_kf=(time.perf_counter()-t)*1000
        knn_f.append(dt_kf)

        # 5. State Check (SHARED — giả lập)
        t=time.perf_counter()
        _=ms or mf  # simulate logic
        dt_st=(time.perf_counter()-t)*1000
        state_t.append(dt_st)

        # 6. DB Save (SHARED — giả lập write overhead)
        t=time.perf_counter()
        _=str(ms)  # simulate serialization
        dt_db=(time.perf_counter()-t)*1000
        db_t.append(dt_db)

        # Total per backend
        total_s.append(dt_det+dt_bf+dt_es+dt_ks+dt_st+dt_db)
        total_f.append(dt_det+dt_bf+dt_ef+dt_kf+dt_st+dt_db)

        if (idx+1)%200==0 or (idx+1)==total:
            print(f"    [{idx+1}/{total}] faces={faces} errors={errors}")

    return {
        "detection":stats(det_t), "best_frame":stats(bf_t),
        "emb_sface":stats(emb_s), "emb_facelivt":stats(emb_f),
        "knn_sface":stats(knn_s), "knn_facelivt":stats(knn_f),
        "state_check":stats(state_t), "db_save":stats(db_t),
        "total_sface":stats(total_s), "total_facelivt":stats(total_f),
        "n_total":total, "n_faces":faces, "n_errors":errors,
    }

# ── Reports ──
def print_report(r, s_dim, f_dim, sys_info, source):
    print(f"\n{'='*85}")
    print(f"  ⏱️  BENCHMARK LATENCY — Pipeline với 2 backends")
    print(f"{'='*85}")
    print(f"  Thời gian  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Platform   : {sys_info['platform']} ({sys_info['machine']})")
    print(f"  OpenCV     : {sys_info['opencv']}   ONNX RT: {sys_info['onnxruntime']}")
    print(f"  Dataset    : {source}")
    print(f"  Tổng ảnh   : {r['n_total']}")
    print(f"  Có mặt     : {r['n_faces']} ({r['n_faces']/max(r['n_total'],1)*100:.1f}%)")
    print(f"  Lỗi đọc    : {r['n_errors']}")
    print(f"{'-'*85}")

    def row(label, s_key, f_key=None, shared=False):
        s=r[s_key]
        if shared or f_key is None:
            print(f"    {label:<35} {s['mean']:>7.2f}ms {s['med']:>7.2f}ms {s['p95']:>7.2f}ms {s['min']:>7.2f}ms {s['max']:>7.2f}ms")
        else:
            f=r[f_key]
            print(f"    {label}")
            print(f"      SFace ({s_dim}d)                    {s['mean']:>7.2f}ms {s['med']:>7.2f}ms {s['p95']:>7.2f}ms {s['min']:>7.2f}ms {s['max']:>7.2f}ms")
            print(f"      FaceLiVT ({f_dim}d)                 {f['mean']:>7.2f}ms {f['med']:>7.2f}ms {f['p95']:>7.2f}ms {f['min']:>7.2f}ms {f['max']:>7.2f}ms")

    print(f"  {'Bước':<35} {'Mean':>8} {'Med':>8} {'P95':>8} {'Min':>8} {'Max':>8}")
    print(f"  {'─'*35} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")

    row("1. Face Detection (YuNet)", "detection", shared=True)
    row("2. Best Frame Selector", "best_frame", shared=True)
    row("3. Face Embedding ⬇", "emb_sface", "emb_facelivt")
    row("4. KNN Top-5 Matching ⬇", "knn_sface", "knn_facelivt")
    row("5. State Check", "state_check", shared=True)
    row("6. DB Save", "db_save", shared=True)

    print(f"  {'─'*35} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    ts=r["total_sface"]; tf=r["total_facelivt"]
    print(f"  ★ TỔNG PIPELINE")
    print(f"      SFace ({s_dim}d)                    {ts['mean']:>7.2f}ms {ts['med']:>7.2f}ms {ts['p95']:>7.2f}ms {ts['min']:>7.2f}ms {ts['max']:>7.2f}ms")
    print(f"      FaceLiVT ({f_dim}d)                 {tf['mean']:>7.2f}ms {tf['med']:>7.2f}ms {tf['p95']:>7.2f}ms {tf['min']:>7.2f}ms {tf['max']:>7.2f}ms")
    print(f"{'='*85}")

    sm,fm=ts['mean'],tf['mean']
    faster="SFace" if sm<fm else "FaceLiVT"
    ratio=max(sm,fm)/max(min(sm,fm),0.01)
    print(f"  {faster} nhanh hơn ~{ratio:.1f}x")
    print(f"  SFace:    ~{1000/max(sm,1):.0f} FPS  │  FaceLiVT: ~{1000/max(fm,1):.0f} FPS")

    for name,tot in [("SFace",sm),("FaceLiVT",fm)]:
        if tot<100: v="✅ Real-time"
        elif tot<200: v="✅ Tốt"
        elif tot<500: v="⚠️ TB"
        else: v="❌ Chậm"
        print(f"  {name:>10}: {v} ({tot:.1f}ms/frame)")
    print()

def save_reports(r, s_dim, f_dim, sys_info, source, out_dir):
    ts_str=datetime.now().strftime("%Y%m%d_%H%M%S")
    # CSV
    cp=out_dir/f"latency_comparison_{ts_str}.csv"
    with open(cp,"w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh)
        w.writerow(["step","scope","mean_ms","median_ms","p95_ms","min_ms","max_ms","count"])
        for key,label in [("detection","Shared"),("best_frame","Shared"),
                          ("emb_sface",f"SFace({s_dim}d)"),("emb_facelivt",f"FaceLiVT({f_dim}d)"),
                          ("knn_sface",f"SFace({s_dim}d)"),("knn_facelivt",f"FaceLiVT({f_dim}d)"),
                          ("state_check","Shared"),("db_save","Shared"),
                          ("total_sface",f"SFace({s_dim}d)"),("total_facelivt",f"FaceLiVT({f_dim}d)")]:
            s=r[key]
            w.writerow([key,label,f"{s['mean']:.2f}",f"{s['med']:.2f}",f"{s['p95']:.2f}",
                        f"{s['min']:.2f}",f"{s['max']:.2f}",s.get('n',0)])
        w.writerow([]); w.writerow(["# METADATA"])
        for k,v in sys_info.items(): w.writerow([k,v])
        w.writerow(["source",source]); w.writerow(["timestamp",datetime.now().isoformat()])
    print(f"  📄 CSV: {cp}")
    # TXT
    tp=out_dir/f"latency_comparison_{ts_str}.txt"
    sm,fm=r["total_sface"]["mean"],r["total_facelivt"]["mean"]
    lines=["="*70,"  BENCHMARK LATENCY: Shared Pipeline + SFace vs FaceLiVT","="*70,
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  {sys_info['platform']}  OpenCV={sys_info['opencv']}  ONNX={sys_info['onnxruntime']}",
        f"  Dataset: {source} ({r['n_total']} images, {r['n_faces']} faces)","-"*70,
        f"  Detection (shared):       {r['detection']['mean']:.1f}ms",
        f"  Best Frame (shared):      {r['best_frame']['mean']:.1f}ms",
        f"  Embedding  SFace:         {r['emb_sface']['mean']:.1f}ms",
        f"  Embedding  FaceLiVT:      {r['emb_facelivt']['mean']:.1f}ms",
        f"  KNN Match  SFace:         {r['knn_sface']['mean']:.1f}ms",
        f"  KNN Match  FaceLiVT:      {r['knn_facelivt']['mean']:.1f}ms",
        f"  State Check (shared):     {r['state_check']['mean']:.1f}ms",
        f"  DB Save (shared):         {r['db_save']['mean']:.1f}ms","-"*70,
        f"  TOTAL SFace ({s_dim}d):      {sm:.1f}ms  ~{1000/max(sm,1):.0f} FPS",
        f"  TOTAL FaceLiVT ({f_dim}d):   {fm:.1f}ms  ~{1000/max(fm,1):.0f} FPS","="*70]
    with open(tp,"w",encoding="utf-8") as fh: fh.write("\n".join(lines))
    print(f"  📄 TXT: {tp}")

# ── Main ──
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--folder",type=str,required=True)
    parser.add_argument("--max",type=int,default=0)
    parser.add_argument("--output",type=str,default="")
    args=parser.parse_args()

    out_dir=Path(args.output) if args.output else PROJECT_ROOT/"benchmarks"
    out_dir.mkdir(exist_ok=True)
    folder=Path(args.folder)
    if not folder.is_absolute(): folder=PROJECT_ROOT/folder

    print("="*65); print("  ⏱️  Benchmark: Shared Pipeline + SFace vs FaceLiVT"); print("="*65)

    print("\n[1/4] Khởi tạo...")
    detector=FaceDetector(); selector=BestFrameSelector(); sys_info=get_sys_info()
    sface=SFaceWrap(); print(f"  SFace:    {sface.embed_dim}-dim")
    facelivt=FaceLiVTWrap(); print(f"  FaceLiVT: {facelivt.embed_dim}-dim")

    print(f"\n[2/4] Thu thập & enroll gallery...")
    images=collect_images(folder,args.max)
    print(f"  📷 {len(images)} ảnh")
    if not images: print("  ❌ Không có ảnh!"); return

    sg,si=enroll_gallery(images,detector,sface)
    print(f"  SFace gallery:    {sg.shape[0]} × {sg.shape[1]}d")
    fg,fi=enroll_gallery(images,detector,facelivt)
    print(f"  FaceLiVT gallery: {fg.shape[0]} × {fg.shape[1]}d")

    print(f"\n[3/4] Benchmark ({len(images)} ảnh)...")
    r=benchmark_all(images,detector,selector,sface,facelivt,sg,si,fg,fi)

    print(f"\n[4/4] Báo cáo...")
    source=str(folder)
    print_report(r,sface.embed_dim,facelivt.embed_dim,sys_info,source)
    save_reports(r,sface.embed_dim,facelivt.embed_dim,sys_info,source,out_dir)
    print(f"  ✅ Hoàn tất!")

if __name__=="__main__": main()
