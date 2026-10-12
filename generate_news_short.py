import os
import subprocess
import time
import wandb
from mlx_video.models.wan_2.generate import generate_video

# --- Configuration ---
MODEL_DIR = "wan21_mlx"
OUTPUT_DIR = "generated_shots"
FINAL_OUTPUT = "final_news_short.mp4"
SEED = 42  # Fixed seed for character consistency
WIDTH = 480
HEIGHT = 854  # 9:16 Aspect Ratio for Shorts
NUM_FRAMES = 65  # ~4 seconds per shot (8n + 1)
STEPS = 20

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Shot List Based on Your Script ---
# Base prompt ensures the anchor/studio looks consistent
BASE_PROMPT = "A professional news anchor sitting in a modern aesthetic studio room, soft blue ambient lighting, minimalist background, news desk, 9:16 vertical video, high quality."

shots = [
    {"id": "HOOK", "prompt": f"{BASE_PROMPT} The anchor welcomes viewers, with abstract blue technology particles floating in the background hologram.", "desc": "Intro Hook"},
    {"id": "S1_CONTEXT", "prompt": f"{BASE_PROMPT} The anchor gestures towards a holographic screen showing old EV battery disposal methods in Japan.", "desc": "S1: Battery Disposal"},
    {"id": "S1_CORE", "prompt": f"{BASE_PROMPT} The anchor explains the new method to recover 90% of lithium, looking serious and informative.", "desc": "S1: Recycling Method"},
    {"id": "S1_TWIST", "prompt": f"{BASE_PROMPT} Close up on anchor nodding, with a macro view of recycling battery components floating in the background hologram.", "desc": "S1: Macro View"},
    {"id": "S2_HOOK", "prompt": f"{BASE_PROMPT} The anchor holds a tablet showing a mobile app interface, discussing building Mac apps without Xcode.", "desc": "S2: Mobile Apps"},
    {"id": "S2_CORE", "prompt": f"{BASE_PROMPT} The anchor types on a floating command line interface hologram, demonstrating coding on a mobile device.", "desc": "S2: Command Line"},
    {"id": "S2_TWIST", "prompt": f"{BASE_PROMPT} The anchor smiles while showing a finished iOS app on a smartphone screen.", "desc": "S2: App Result"},
    {"id": "S3_HOOK", "prompt": f"{BASE_PROMPT} The anchor compares two floating holographic charts labeled 'SpeechAnalyzer' and 'Whisper'.", "desc": "S3: Speech API"},
    {"id": "S3_CORE", "prompt": f"{BASE_PROMPT} The anchor speaks into a microphone, testing the new Apple SpeechAnalyzer API, looking impressed.", "desc": "S3: Live Test"},
    {"id": "CTA", "prompt": f"{BASE_PROMPT} The anchor points to a 'Subscribe' button floating in the air, with abstract blue particles in background.", "desc": "Call to Action"}
]

# --- Initialize W&B ---
wandb.init(project="news-studio-shorts", config={
    "model": MODEL_DIR,
    "resolution": f"{WIDTH}x{HEIGHT}",
    "frames": NUM_FRAMES,
    "seed": SEED,
    "total_shots": len(shots)
})

generated_files = []

print(f"🎬 Starting generation of {len(shots)} shots...")

for i, shot in enumerate(shots):
    filename = f"shot_{i+1:02d}_{shot['id']}.mp4"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    print(f"\n--- Generating Shot {i+1}/{len(shots)}: {shot['id']} ---")
    print(f"Prompt: {shot['prompt']}")
    
    start_time = time.time()
    
    try:
        # Call the MLX generation function
        # Note: generate_video arguments may vary slightly based on your specific mlx-video version
        # If generate_video is not directly importable, we might need to call via subprocess inside the loop
        # Assuming direct function call based on search context:
        generate_video(
            model_dir=MODEL_DIR,
            prompt=shot['prompt'],
            width=WIDTH,
            height=HEIGHT,
            num_frames=NUM_FRAMES,
            steps=STEPS,
            seed=SEED,
            output_path=filepath
        )
        
        gen_time = time.time() - start_time
        
        # Log to W&B
        wandb.log({
            "shot_id": shot['id'],
            "generation_time_sec": gen_time,
            "prompt": shot['prompt'],
            "video": wandb.Video(filepath, fps=16, format="mp4", caption=shot['desc'])
        })
        
        generated_files.append(filepath)
        print(f"✅ Success: {filename} ({gen_time:.2f}s)")
        
    except Exception as e:
        print(f"❌ Error generating {shot['id']}: {e}")
        wandb.log({"error": str(e), "shot_id": shot['id']})
        # Continue to next shot or break depending on preference
        continue

# --- Merge Videos ---
if len(generated_files) > 0:
    print("\n🔗 Merging videos...")
    list_file = "file_list.txt"
    
    # Create file list for ffmpeg
    with open(list_file, "w") as f:
        for file in generated_files:
            f.write(f"file '{os.path.abspath(file)}'\n")
    
    # Run ffmpeg
    merge_cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        FINAL_OUTPUT
    ]
    
    subprocess.run(merge_cmd, check=True)
    
    # Log final video to W&B
    wandb.log({
        "final_video": wandb.Video(FINAL_OUTPUT, fps=16, format="mp4", caption="Complete News Short")
    })
    
    print(f"🎉 Done! Final video saved to: {FINAL_OUTPUT}")
else:
    print("❌ No videos generated. Skipping merge.")

wandb.finish()   