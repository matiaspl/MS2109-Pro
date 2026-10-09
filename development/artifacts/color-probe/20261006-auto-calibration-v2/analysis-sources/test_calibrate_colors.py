"""File-only checks for calibration's clipping penalty and response prediction."""
import unittest
from io import BytesIO
import numpy as np
from PIL import Image
from calibrate_colors import chart, jpeg_headers, metrics, predict, targets


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.rgb=np.array([p["rgb"] for p in chart()["patches"]],float)

    def score(self,values):
        return metrics(values,np.repeat(values[:,None,:],3,axis=1),self.rgb,"full")

    def test_wide_but_clipped_ramp_loses(self):
        ideal=targets(self.rgb,"full")
        clipped=ideal.copy();clipped[:,0]=np.clip(ideal[:,0]*1.6-76,0,255)
        good,bad=self.score(ideal),self.score(clipped)
        self.assertEqual(bad["gray_span"],255)
        self.assertGreater(bad["gray_false_clipped_input_levels"],80)
        self.assertGreater(bad["score_loss"],good["score_loss"]+100)

    def test_preserved_chroma_is_not_scored_as_full(self):
        ideal=targets(self.rgb,"preserve")
        pixels=np.repeat(ideal[:,None,:],3,axis=1)
        self.assertAlmostEqual(metrics(ideal,pixels,self.rgb,"preserve")["score_loss"],0)
        self.assertGreater(metrics(ideal,pixels,self.rgb,"full")["score_loss"],10)

    def test_local_model_predicts_before_search(self):
        def sample(b,c):
            y=(16+219*np.arange(256)/255)*c/128+(b-128)
            return {"controls":{"brightness_ui":b,"contrast":c},"formats":{"yuy2":{"median_values":np.c_[y,np.ones(256)*128,np.ones(256)*128].tolist()}}}
        predicted=predict(sample(128,128),sample(113,128),sample(128,136))
        self.assertAlmostEqual(predicted["predicted_contrast"],128*255/219)
        self.assertAlmostEqual(predicted["predicted_brightness_ui"],128-16*255/219)

    def test_chart_has_chroma_extrema_and_all_ramp_codes(self):
        p=chart()["patches"]
        self.assertEqual(len(p),1920)
        for i in range(7): self.assertEqual([x["code"] for x in p[i*256:(i+1)*256]],list(range(256)))
        ideal=targets(self.rgb,"full")
        np.testing.assert_allclose(ideal.min(axis=0),[0,0.5,0.5],atol=1e-12)
        np.testing.assert_allclose(ideal.max(axis=0),[255,255,255],atol=1e-12)

    def test_header_audit_detects_missing_huffman_tables(self):
        stream=BytesIO();Image.new("RGB",(32,32),(70,120,200)).save(stream,format="JPEG")
        payload=stream.getvalue()
        self.assertTrue(jpeg_headers(payload)["referenced_coding_tables_present"])
        output=bytearray(payload[:2]);i=2
        while i<len(payload):
            code=payload[i+1];length=int.from_bytes(payload[i+2:i+4],"big")
            if code==0xda:
                output.extend(payload[i:]);break
            if code!=0xc4:output.extend(payload[i:i+2+length])
            i+=2+length
        self.assertFalse(jpeg_headers(bytes(output))["referenced_coding_tables_present"])


if __name__=="__main__":unittest.main()
