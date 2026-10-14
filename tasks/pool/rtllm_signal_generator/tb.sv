`timescale 1ns/1ps
module tb;
    // 转换器新增：一个样本表示一次完整上游测试台判定。
    integer benchmark_error = 0;
    integer benchmark_completed = 0;
    task benchmark_done(input integer passed);
      begin
        benchmark_completed = 1;
        $display("Mismatches: %0d in 1 samples", (!passed || benchmark_error != 0));
        $finish;
      end
    endtask
    final begin
      if (!benchmark_completed)
        $display("Mismatches: 1 in 0 samples");
    end
    initial begin
      #100000000;
      $display("TIMEOUT: upstream testbench did not complete");
      $finish;
    end

reg				clk,rst_n;
wire[4:0]		wave;

TopModule uut(
				.clk(clk),
				.rst_n(rst_n),
				.wave(wave)
				);

reg[31:0]reference[0:99];

integer i = 0;
integer error = 0;
// integer outfile;
initial begin
      reference[0] = 'h00;
reference[1] = 'h01;
reference[2] = 'h02;
reference[3] = 'h03;
reference[4] = 'h04;
reference[5] = 'h05;
reference[6] = 'h06;
reference[7] = 'h07;
reference[8] = 'h08;
reference[9] = 'h09;
reference[10] = 'h0a;
reference[11] = 'h0b;
reference[12] = 'h0c;
reference[13] = 'h0d;
reference[14] = 'h0e;
reference[15] = 'h0f;
reference[16] = 'h10;
reference[17] = 'h11;
reference[18] = 'h12;
reference[19] = 'h13;
reference[20] = 'h14;
reference[21] = 'h15;
reference[22] = 'h16;
reference[23] = 'h17;
reference[24] = 'h18;
reference[25] = 'h19;
reference[26] = 'h1a;
reference[27] = 'h1b;
reference[28] = 'h1c;
reference[29] = 'h1d;
reference[30] = 'h1e;
reference[31] = 'h1f;
reference[32] = 'h1f;
reference[33] = 'h1e;
reference[34] = 'h1d;
reference[35] = 'h1c;
reference[36] = 'h1b;
reference[37] = 'h1a;
reference[38] = 'h19;
reference[39] = 'h18;
reference[40] = 'h17;
reference[41] = 'h16;
reference[42] = 'h15;
reference[43] = 'h14;
reference[44] = 'h13;
reference[45] = 'h12;
reference[46] = 'h11;
reference[47] = 'h10;
reference[48] = 'h0f;
reference[49] = 'h0e;
reference[50] = 'h0d;
reference[51] = 'h0c;
reference[52] = 'h0b;
reference[53] = 'h0a;
reference[54] = 'h09;
reference[55] = 'h08;
reference[56] = 'h07;
reference[57] = 'h06;
reference[58] = 'h05;
reference[59] = 'h04;
reference[60] = 'h03;
reference[61] = 'h02;
reference[62] = 'h01;
reference[63] = 'h00;
reference[64] = 'h00;
reference[65] = 'h01;
reference[66] = 'h02;
reference[67] = 'h03;
reference[68] = 'h04;
reference[69] = 'h05;
reference[70] = 'h06;
reference[71] = 'h07;
reference[72] = 'h08;
reference[73] = 'h09;
reference[74] = 'h0a;
reference[75] = 'h0b;
reference[76] = 'h0c;
reference[77] = 'h0d;
reference[78] = 'h0e;
reference[79] = 'h0f;
reference[80] = 'h10;
reference[81] = 'h11;
reference[82] = 'h12;
reference[83] = 'h13;
reference[84] = 'h14;
reference[85] = 'h15;
reference[86] = 'h16;
reference[87] = 'h17;
reference[88] = 'h18;
reference[89] = 'h19;
reference[90] = 'h1a;
reference[91] = 'h1b;
reference[92] = 'h1c;
reference[93] = 'h1d;
reference[94] = 'h1e;
reference[95] = 'h1f;
reference[96] = 'h1f;
reference[97] = 'h1e;
reference[98] = 'h1d;
reference[99] = 'h1c;
			clk = 0;
      rst_n = 0;
			#10
      rst_n =1;
      // outfile = $fopen("tri_gen.txt", "w");
			repeat(100) begin
        // $fwrite(outfile, "%h\n", wave);
        // $display(wave);
        error=(wave==reference[i])?error:error+1;
        #10;
        i = i+1;
      end
      // $fclose(outfile);
      if(error==0)
      begin
        begin $display("===========Your Design Passed==========="); benchmark_done(1); end
            end
      else
      begin
        begin $display("===========Error==========="); benchmark_done(0); end
      end
      $finish;
end
 
always #5 clk =~clk;
 
endmodule
