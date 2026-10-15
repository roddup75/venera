import unittest
import numpy as np
import pandas as pd
from bucket_sampler import bucket_migration

class BucketMigrationTests(unittest.TestCase):
    def setUp(self):
        self.buckets=pd.DataFrame({'lower':[0,.1,.5],'upper':[.1,.5,1.], 'label':['0–10%','10–50%','50–100%']})
        self.book=pd.DataFrame({'Baseline order/ADV':[.05,.25,.75,1.], 'Sampled orders':[10,4,2,1]})

    def test_boundaries_overflow_and_conservation(self):
        distribution,flows=bucket_migration(self.book,self.buckets,3.4)
        expected=[[10,4,2,1],[0,10,4,3],[0,10,4,3]]
        for stage in range(3):
            rows=distribution[distribution.Stage==stage]
            np.testing.assert_array_equal(rows.Trades,expected[stage])
            self.assertEqual(rows.Trades.sum(),17)
            self.assertAlmostEqual(rows['Trade share (%)'].sum(),100.)
            self.assertAlmostEqual(rows['AUM (USD bn)'].iloc[0],3.4*(stage+1))
        self.assertEqual(flows[flows['From stage']==0].Trades.sum(),17)
        self.assertEqual(flows[flows['From stage']==1].Trades.sum(),17)
        self.assertTrue((flows['To bucket']>=flows['From bucket']).all())
        self.assertEqual(distribution.Bucket.iloc[-1],'≥100%')
        for _,row in distribution.iterrows():
            stage=int(row.Stage); bucket=int(row['Bucket index'])
            if stage<2:
                self.assertEqual(flows[(flows['From stage']==stage)&(flows['From bucket']==bucket)].Trades.sum(),row.Trades)
            if stage>0:
                self.assertEqual(flows[(flows['To stage']==stage)&(flows['To bucket']==bucket)].Trades.sum(),row.Trades)

    def test_inspection_aum_independence_and_validation(self):
        before=bucket_migration(self.book,self.buckets,.5)[0]
        book=self.book.assign(**{'Order/ADV at selected AUM':[10,20,30,40]})
        after=bucket_migration(book,self.buckets,.5)[0]
        pd.testing.assert_frame_equal(before,after)
        bad=self.buckets.copy();bad.loc[1,'lower']=.2
        with self.assertRaises(ValueError): bucket_migration(self.book,bad,1.)
        with self.assertRaises(ValueError): bucket_migration(self.book.assign(**{'Sampled orders':0}),self.buckets,1.)
