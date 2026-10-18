# 段階 0: XVF3800 の録音・再生とファームウェア更新

2026-10-18 実施。Pi 5（Ubuntu 24.04, kernel 6.8.0-raspi）。

## 結果

| 完了条件 | 結果 |
|---|---|
| 録った声がそのまま再生できる | OK（`scripts/audio_check.sh`） |
| ファームウェアを最新にする | v2.0.6 → v2.1.1（USB 2ch 版） |
| ソフトリブート後も録音が正常 | OK（更新前・更新後とも各 1 回確認） |

## デバイス

- USB ID `2886:001a`、ALSA のカード名 `Array`（番号は起動ごとに変わるので名前で指定する）
- 録音・再生とも S16_LE / 16 kHz / 2ch。録音は ch1 が音声処理済みの出力（STT 用）、ch2 は ch1 より小さい
- ミキサー: `PCM`（再生、初期値 -20dB）、`Headset`（録音、初期値 0dB）

## セットアップ手順

```sh
sudo apt-get install -y alsa-utils dfu-util
```

### ファームウェア更新

公式: https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/tree/master/xmos_firmwares/usb

```sh
F=respeaker_xvf3800_usb_dfu_firmware_v2.1.1.bin
curl -fsSL -o ~/xvf3800-fw/$F https://raw.githubusercontent.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/master/xmos_firmwares/usb/$F
sudo dfu-util -l                                   # "reSpeaker DFU Upgrade" (alt=1) が見えること
sudo dfu-util -R -e -a 1 -D ~/xvf3800-fw/$F        # "Done!" で完了。"Invalid DFU suffix" 警告は無視してよい
lsusb -v -d 2886:001a | grep bcdDevice             # 2.11 = v2.1.1
```

- `dfu-util` は sudo が必要（udev ルール未設定のため `LIBUSB_ERROR_ACCESS`）
- v2.0.10 で「USB バスリセット後に音声が復旧しない／Linux で EOVERFLOW」不具合が修正されている。ソフトリブートは電源を切らずに USB だけリセットするので、この版以上を使う

### 再生音量

`PCM` を 0dB に固定し、音量はスピーカーのつまみで調整する。保存しないとリブートで -20dB に戻る。

```sh
amixer -c Array -q sset "PCM",0 100% && amixer -c Array -q sset "PCM",1 100%
sudo alsactl store                                 # /var/lib/alsa/asound.state に保存
```

## 確認方法

```sh
~/raspi-smart-speaker/scripts/audio_check.sh 5     # 5 秒録音 → レベル表示 → 再生
```

- 話した場合の ch1 の目安: ピーク 1 万〜3 万、RMS -20〜-35 dBFS。32767 付近は音割れなので少し離れる
- 周りの音だけの場合はピーク 100〜2000 程度
