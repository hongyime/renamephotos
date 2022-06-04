import os,sys,random,string

folder = input('Where are the photos: ')
for count, filename in enumerate(os.listdir(folder)):
        src =f"{folder}/{filename}"  # foldername/filename, if .py file is outside folder
        if filename.endswith('.jpg'):
                ext = '.jpg'
        elif filename.endswith('.jpeg'):
                ext = '.jpeg'
        elif filename.endswith('.png'):
                ext = '.png'
        elif filename.endswith('.JPG'):
                ext = '.JPG'
#         elif filename.endswith('.mov'):
#                 ext = '.mov'
#         elif filename.endswith('.mp4'):
#                 ext = '.mp4'
#         elif filename.endswith('.mp3'):
#                 ext = '.mp3'
        else:
                continue
        rand = "".join(random.sample(string.ascii_lowercase + string.digits, 20)) + ext
        dst =f"{folder}/{rand}"
        os.rename(src, dst)
        print(f'renamed {filename} to {rand}')
        
print('All done')


